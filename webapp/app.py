"""FastAPI app para administrar el entorno de impresión MKP."""

from __future__ import annotations

import base64
import binascii
import configparser
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import subprocess
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Tuple

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = BASE_DIR / "logs" / "listener"
WEBHOOK_LOG_DIR = BASE_DIR / "logs" / "webhook"
WEBHOOK_LOG_PATH = WEBHOOK_LOG_DIR / "cups_events.jsonl"
WEBHOOK_ENDPOINT = "/api/cups/webhook"
WEBHOOK_TOKEN = os.environ.get("MKP_CUPS_WEBHOOK_TOKEN")
WEBHOOK_MAX_RETURN = int(os.environ.get("MKP_CUPS_WEBHOOK_MAX", "200"))
INI_PATH = BASE_DIR / "watch_print.ini"
PPD_DIR = Path("/etc/cups/ppd")
SUDO_BIN = os.environ.get("MKP_SUDO_BIN", "sudo")
SYSTEM_PATH = os.environ.get(
    "MKP_SYSTEM_PATH",
    "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
)
LPSTAT_BIN = os.environ.get("MKP_LPSTAT", shutil.which("lpstat") or "/usr/bin/lpstat")
LPADMIN_BIN = os.environ.get("MKP_LPADMIN", shutil.which("lpadmin") or "/usr/sbin/lpadmin")
LPOPTIONS_BIN = os.environ.get("MKP_LPOPTIONS", shutil.which("lpoptions") or "/usr/bin/lpoptions")
SYSTEMCTL_BIN = os.environ.get("MKP_SYSTEMCTL", shutil.which("systemctl") or "/usr/bin/systemctl")

SERVICE_MAP = {
    "listener": "print-listener.service",
    "cups": "cups",
}

RELEVANT_OPTIONS = {
    "media",
    "print-scaling",
    "fit-to-page",
    "scaling",
    "sides",
    "copies",
}

WEEKDAY_LABELS = [
    "Lunes",
    "Martes",
    "Miércoles",
    "Jueves",
    "Viernes",
    "Sábado",
    "Domingo",
]

IPP_JOB_STATE_LABELS = {
    3: "PENDING",
    4: "HELD",
    5: "PROCESSING",
    6: "STOPPED",
    7: "CANCELED",
    8: "ABORTED",
    9: "COMPLETED",
}

LOG_TIMESTAMP_PATTERN = re.compile(
    r"^\[(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})(?:\.\d+|\.%f)?\]"
)
SEND_EVENT_PATTERN = re.compile(r"Enviando (.+?) a la impresora", re.UNICODE)
COMPLETE_EVENT_PATTERN = re.compile(r"Impresión completada: (.+)", re.UNICODE)
ORIGIN_PREFIX_PATTERN = re.compile(r"^([A-Za-z]+)")


class ClonePrinterRequest(BaseModel):
    source: str = Field(..., min_length=1, max_length=50)
    target: str = Field(..., min_length=1, max_length=50)
    target_uri: str = Field(..., min_length=4)
    description: str | None = Field(None, max_length=120)
    add_alias: bool = True


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1, max_length=200)


app = FastAPI(title="MKP Admin", version="1.1.0")

STATIC_DIR = Path(__file__).resolve().parent / "static"
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def run_command(cmd: List[str], *, use_sudo: bool = False) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PATH"] = SYSTEM_PATH
    full_cmd = ([SUDO_BIN, "-n"] + cmd) if use_sudo else cmd
    return subprocess.run(full_cmd, capture_output=True, text=True, check=False, env=env)


BASIC_USER = os.environ.get("MKP_BASIC_USER")
BASIC_SECRET = os.environ.get("MKP_BASIC_PASSWORD_HASH")
PBKDF_ITER = int(os.environ.get("MKP_BASIC_PBKDF_ITER", "600000"))
SESSION_SECRET_RAW = os.environ.get("MKP_SESSION_SECRET") or (BASIC_SECRET or "mkp-session-secret")
SESSION_SECRET_KEY = SESSION_SECRET_RAW.encode("utf-8")
SESSION_COOKIE_NAME = os.environ.get("MKP_SESSION_COOKIE", "mkp_session")
SESSION_DURATION_SECONDS = int(os.environ.get("MKP_SESSION_DURATION", str(8 * 3600)))
SESSION_COOKIE_SECURE = os.environ.get("MKP_SESSION_COOKIE_SECURE", "false").lower() in {"1", "true", "yes"}


def verify_basic_password(password: str) -> bool:
    if not BASIC_SECRET:
        return False
    try:
        iterations_str, salt_hex, stored_hex = BASIC_SECRET.split(":", 2)
        iterations = int(iterations_str)
    except ValueError:
        return False
    salt = bytes.fromhex(salt_hex)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return secrets.compare_digest(stored_hex, derived.hex())


def needs_auth(path: str) -> bool:
    if not BASIC_USER or not BASIC_SECRET:
        return False
    if path == WEBHOOK_ENDPOINT:
        return False
    if path in {"/", "/favicon.svg", "/favicon.ico"}:
        return False
    if path.startswith("/static"):
        return False
    if path.startswith("/api/auth/login") or path.startswith("/api/auth/logout"):
        return False
    return True


def create_session_token(username: str) -> str:
    issued_at = str(int(time.time()))
    payload = f"{username}|{issued_at}"
    signature = hmac.new(SESSION_SECRET_KEY, payload.encode(), hashlib.sha256).hexdigest()
    token = base64.urlsafe_b64encode(f"{payload}|{signature}".encode()).decode()
    return token


def verify_session_token(token: str) -> str | None:
    try:
        decoded = base64.urlsafe_b64decode(token.encode()).decode()
        username, issued_at, signature = decoded.split("|", 2)
    except (ValueError, binascii.Error):
        return None
    expected = hmac.new(
        SESSION_SECRET_KEY,
        f"{username}|{issued_at}".encode(),
        hashlib.sha256,
    ).hexdigest()
    if not secrets.compare_digest(expected, signature):
        return None
    try:
        issued_int = int(issued_at)
    except ValueError:
        return None
    if time.time() - issued_int > SESSION_DURATION_SECONDS:
        return None
    return username


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=token,
        httponly=True,
        max_age=SESSION_DURATION_SECONDS,
        expires=SESSION_DURATION_SECONDS,
        secure=SESSION_COOKIE_SECURE,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")


def get_session_user_from_request(request: Request) -> str | None:
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        return None
    return verify_session_token(token)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    request.state.user = None
    if not needs_auth(request.url.path):
        return await call_next(request)

    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if session_token:
        session_user = verify_session_token(session_token)
        if session_user:
            request.state.user = session_user
            return await call_next(request)

    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Basic "):
        try:
            decoded = base64.b64decode(auth_header.split(" ", 1)[1]).decode()
        except Exception:
            return JSONResponse({"detail": "No autorizado"}, status_code=401)

        username, _, password = decoded.partition(":")
        if secrets.compare_digest(username, BASIC_USER or "") and verify_basic_password(password):
            request.state.user = username
            return await call_next(request)

    return JSONResponse({"detail": "No autorizado"}, status_code=401)


def summarize_command(result: subprocess.CompletedProcess) -> Dict[str, str | int]:
    return {
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
        "command": " ".join(result.args),
    }


def parse_systemctl(unit: str) -> Dict[str, str | int]:
    show = run_command(
        [
            SYSTEMCTL_BIN,
            "show",
            unit,
            "--property=ActiveState,SubState,UnitFileState,MainPID,Description",
            "--no-pager",
        ],
        use_sudo=True,
    )
    info: Dict[str, str | int] = {"unit": unit, "returncode": show.returncode}
    for line in show.stdout.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            info[key] = value
    status = run_command([SYSTEMCTL_BIN, "status", unit, "--no-pager", "--lines=25"], use_sudo=True)
    info["status_text"] = status.stdout.strip() or status.stderr.strip()
    info["status_returncode"] = status.returncode
    return info


def read_tail(path: Path, max_lines: int = 100) -> List[str]:
    if max_lines <= 0:
        max_lines = 100
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        lines = fh.readlines()
    return [line.rstrip("\n") for line in lines[-max_lines:]]


def latest_log_file() -> Path | None:
    if not LOG_DIR.exists():
        return None
    base_log = LOG_DIR / "print_service.log"
    if base_log.exists():
        return base_log
    log_files = sorted(LOG_DIR.glob("print_service_*.log"))
    return log_files[-1] if log_files else None


def week_date_range(today: date | None = None) -> Tuple[date, date]:
    if today is None:
        today = date.today()
    start = today - timedelta(days=today.weekday())
    end = start + timedelta(days=6)
    return start, end


def collect_week_log_paths(days: List[date]) -> List[Path]:
    if not LOG_DIR.exists():
        return []
    dated_paths = []
    for day in days:
        candidate = LOG_DIR / f"print_service_{day.isoformat()}.log"
        if candidate.exists():
            dated_paths.append(candidate)
    dated_paths.sort()
    base_log = LOG_DIR / "print_service.log"
    if base_log.exists():
        dated_paths.append(base_log)
    return dated_paths


def parse_log_timestamp(line: str) -> datetime | None:
    match = LOG_TIMESTAMP_PATTERN.match(line)
    if not match:
        return None
    timestamp = f"{match.group(1)} {match.group(2)}"
    try:
        return datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def extract_log_message(line: str) -> str | None:
    parts = line.split("] ", 3)
    if len(parts) < 4:
        return None
    return parts[3].strip()


def normalize_origin(job_name: str) -> str:
    """Obtiene el origen agrupado (MKP, FPRINT, etc.) a partir del nombre del archivo."""
    if not job_name:
        return "OTROS"
    base_name = os.path.basename(job_name)
    prefix = base_name.split("_", 1)[0].strip().upper()
    if not prefix:
        return "OTROS"
    match = ORIGIN_PREFIX_PATTERN.match(prefix)
    if match:
        return match.group(1)
    return prefix


def increment_origin_counter(
    origin_map: Dict[str, Dict[str, int]],
    origin: str,
    field: str,
) -> None:
    entry = origin_map.setdefault(origin, {"sent": 0, "completed": 0})
    entry[field] = entry.get(field, 0) + 1


def merge_origin_counters(
    target: Dict[str, Dict[str, int]],
    source: Dict[str, Dict[str, int]],
) -> None:
    for origin, counts in source.items():
        dest = target.setdefault(origin, {"sent": 0, "completed": 0})
        dest["sent"] = dest.get("sent", 0) + counts.get("sent", 0)
        dest["completed"] = dest.get("completed", 0) + counts.get("completed", 0)


def build_weekly_print_stats(today: date | None = None) -> Dict[str, object]:
    start, end = week_date_range(today)
    days = [start + timedelta(days=i) for i in range(7)]
    stats_map: Dict[date, Dict[str, object]] = {}
    for day in days:
        stats_map[day] = {
            "sent": 0,
            "completed": 0,
            "duration_total": 0.0,
            "duration_count": 0,
            "duration_min": None,
            "duration_max": None,
            "origins": {},
        }

    job_starts: Dict[str, datetime] = {}
    for log_path in collect_week_log_paths(days):
        try:
            with log_path.open("r", encoding="utf-8", errors="replace") as handle:
                for line in handle:
                    timestamp = parse_log_timestamp(line)
                    if not timestamp:
                        continue
                    day_key = timestamp.date()
                    if day_key not in stats_map:
                        continue
                    message = extract_log_message(line)
                    if not message:
                        continue

                    send_match = SEND_EVENT_PATTERN.search(message)
                    if send_match:
                        job_name = send_match.group(1).strip()
                        if job_name:
                            job_starts[job_name] = timestamp
                            stats_map[day_key]["sent"] = stats_map[day_key]["sent"] + 1
                            origin = normalize_origin(job_name)
                            increment_origin_counter(stats_map[day_key]["origins"], origin, "sent")
                        continue

                    complete_match = COMPLETE_EVENT_PATTERN.search(message)
                    if complete_match:
                        job_name = complete_match.group(1).strip()
                        if not job_name:
                            continue
                        stats_map[day_key]["completed"] = stats_map[day_key]["completed"] + 1
                        origin = normalize_origin(job_name)
                        increment_origin_counter(stats_map[day_key]["origins"], origin, "completed")
                        start_time = job_starts.pop(job_name, None)
                        if start_time:
                            duration = (timestamp - start_time).total_seconds()
                            if duration >= 0:
                                stats = stats_map[day_key]
                                stats["duration_total"] = stats["duration_total"] + duration
                                stats["duration_count"] = stats["duration_count"] + 1
                                stats["duration_min"] = (
                                    duration
                                    if stats["duration_min"] is None
                                    else min(stats["duration_min"], duration)
                                )
                                stats["duration_max"] = (
                                    duration
                                    if stats["duration_max"] is None
                                    else max(stats["duration_max"], duration)
                                )
        except OSError:
            continue

    totals = {
        "sent": 0,
        "completed": 0,
        "duration_total": 0.0,
        "duration_count": 0,
        "duration_min": None,
        "duration_max": None,
        "origins": {},
    }
    days_payload: List[Dict[str, object]] = []
    for day in days:
        stats = stats_map[day]
        totals["sent"] += stats["sent"]
        totals["completed"] += stats["completed"]
        totals["duration_total"] += stats["duration_total"]
        totals["duration_count"] += stats["duration_count"]
        if stats["duration_min"] is not None:
            totals["duration_min"] = (
                stats["duration_min"]
                if totals["duration_min"] is None
                else min(totals["duration_min"], stats["duration_min"])
            )
        if stats["duration_max"] is not None:
            totals["duration_max"] = (
                stats["duration_max"]
                if totals["duration_max"] is None
                else max(totals["duration_max"], stats["duration_max"])
            )
        merge_origin_counters(totals["origins"], stats["origins"])

        duration_count = stats["duration_count"]
        avg_duration = (
            stats["duration_total"] / duration_count if duration_count else None
        )
        days_payload.append(
            {
                "date": day.isoformat(),
                "weekday": WEEKDAY_LABELS[day.weekday()],
                "sent": stats["sent"],
                "completed": stats["completed"],
                "origins": {
                    origin: counts.copy()
                    for origin, counts in stats["origins"].items()
                },
                "duration": {
                    "min_seconds": stats["duration_min"],
                    "avg_seconds": avg_duration,
                    "max_seconds": stats["duration_max"],
                    "samples": duration_count,
                },
            }
        )

    overall_avg = (
        totals["duration_total"] / totals["duration_count"]
        if totals["duration_count"]
        else None
    )

    return {
        "range": {"start": start.isoformat(), "end": end.isoformat()},
        "generated_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "days": days_payload,
        "totals": {
            "sent": totals["sent"],
            "completed": totals["completed"],
            "origins": {
                origin: counts.copy() for origin, counts in totals["origins"].items()
            },
            "avg_duration_seconds": overall_avg,
            "min_duration_seconds": totals["duration_min"],
            "max_duration_seconds": totals["duration_max"],
            "samples": totals["duration_count"],
        },
    }


def parse_lpstat() -> List[Dict[str, str]]:
    listing = run_command([LPSTAT_BIN, "-p", "-l"], use_sudo=True)
    if listing.returncode != 0:
        raise HTTPException(status_code=500, detail=listing.stderr.strip() or "lpstat falló")

    printers: List[Dict[str, str]] = []
    current: Dict[str, str] | None = None
    for raw_line in listing.stdout.splitlines():
        line = raw_line.rstrip()
        if not line:
            continue
        if line.startswith("printer "):
            if current:
                printers.append(current)
            parts = line.split(None, 3)
            status_text = parts[3] if len(parts) > 3 else ""
            current = {
                "name": parts[1],
                "state": status_text.strip(),
            }
        elif current and ":" in line:
            key, value = line.split(":", 1)
            current[key.strip()] = value.strip()
    if current:
        printers.append(current)
    return printers


def extract_options(raw: str) -> Dict[str, str]:
    options: Dict[str, str] = {}
    for token in raw.split():
        if "=" not in token:
            continue
        key, value = token.split("=", 1)
        if key in RELEVANT_OPTIONS and value:
            options[key] = value
    return options


def append_printer_alias(printer: str) -> bool:
    alias_line = f"{printer} = {printer}"
    text = INI_PATH.read_text(encoding="utf-8") if INI_PATH.exists() else ""
    if alias_line in text:
        return False

    lines = text.splitlines()
    if not lines:
        lines = ["[Printers]", alias_line]
    else:
        try:
            start = next(i for i, line in enumerate(lines) if line.strip() == "[Printers]")
        except StopIteration:
            lines.extend(["", "[Printers]", alias_line])
        else:
            insert_at = start + 1
            while insert_at < len(lines) and not lines[insert_at].lstrip().startswith("["):
                insert_at += 1
            lines.insert(insert_at, alias_line)

    INI_PATH.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return True


def load_printer_aliases() -> Dict[str, str]:
    config = configparser.ConfigParser()
    config.optionxform = str
    config.read(INI_PATH, encoding="utf-8")
    if not config.has_section("Printers"):
        return {}
    return dict(config.items("Printers"))


def printer_from_uri(uri: str | None) -> str | None:
    if not uri:
        return None
    clean = uri.rstrip("/")
    if "/" not in clean:
        return clean or None
    return clean.rsplit("/", 1)[-1] or clean


def job_state_label(state_value: Any) -> str:
    if state_value is None:
        return "UNKNOWN"
    try:
        state_int = int(state_value)
    except (TypeError, ValueError):
        return str(state_value)
    return IPP_JOB_STATE_LABELS.get(state_int, str(state_int))


def to_iso_timestamp(raw_value: Any) -> str | None:
    if raw_value is None:
        return None
    if isinstance(raw_value, (int, float)):
        try:
            return datetime.utcfromtimestamp(raw_value).replace(microsecond=0).isoformat() + "Z"
        except (OSError, OverflowError, ValueError):
            return None
    if isinstance(raw_value, str):
        trimmed = raw_value.strip()
        if not trimmed:
            return None
        if trimmed.isdigit():
            try:
                epoch = int(trimmed)
                return datetime.utcfromtimestamp(epoch).replace(microsecond=0).isoformat() + "Z"
            except (OSError, OverflowError, ValueError):
                return trimmed
        return trimmed
    return None


def append_webhook_event(record: Dict[str, Any]) -> None:
    WEBHOOK_LOG_DIR.mkdir(parents=True, exist_ok=True)
    with WEBHOOK_LOG_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_webhook_events(max_entries: int = 50) -> List[Dict[str, Any]]:
    if max_entries <= 0:
        max_entries = 50
    if WEBHOOK_MAX_RETURN > 0:
        max_entries = min(max_entries, WEBHOOK_MAX_RETURN)
    if not WEBHOOK_LOG_PATH.exists():
        return []
    lines = read_tail(WEBHOOK_LOG_PATH, max_lines=max_entries)
    events: List[Dict[str, Any]] = []
    for line in lines:
        text = line.strip()
        if not text:
            continue
        try:
            events.append(json.loads(text))
        except json.JSONDecodeError:
            continue
    events.sort(key=lambda item: item.get("received_at") or item.get("event_time") or "", reverse=True)
    return events


@app.post(WEBHOOK_ENDPOINT)
async def cups_webhook(request: Request):
    if WEBHOOK_TOKEN:
        provided = request.headers.get("X-CUPS-Token")
        if not provided or not secrets.compare_digest(provided, WEBHOOK_TOKEN):
            raise HTTPException(status_code=401, detail="Token de webhook inválido.")
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"JSON inválido: {exc}") from exc

    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="El cuerpo debe ser un objeto JSON.")

    attributes = payload.get("event-notification-attributes-tag")
    if isinstance(attributes, list):
        attributes = attributes[0]
    event_block = attributes if isinstance(attributes, dict) else payload

    event_type = event_block.get("notify-subscribed-event") or event_block.get("event") or "unknown"
    job_id = event_block.get("notify-job-id") or event_block.get("job-id")
    printer_name = event_block.get("printer-name") or printer_from_uri(
        event_block.get("notify-printer-uri") or event_block.get("printer-uri")
    )
    job_state = event_block.get("job-state")
    job_name = event_block.get("job-name") or event_block.get("document-name")
    job_state_reasons = event_block.get("job-state-reasons")
    sequence = event_block.get("notify-sequence-number")
    event_timestamp = to_iso_timestamp(
        event_block.get("notify-time") or event_block.get("time-at-event")
    )
    source_ip = request.client.host if request.client else None
    username = (
        event_block.get("job-originating-user-name")
        or event_block.get("notify-user-data")
        or event_block.get("user-name")
    )

    record = {
        "received_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "event": event_type,
        "printer": printer_name,
        "job_id": job_id,
        "job_name": job_name,
        "job_state": job_state,
        "job_state_label": job_state_label(job_state),
        "job_state_reasons": job_state_reasons,
        "sequence": sequence,
        "event_time": event_timestamp,
        "username": username,
        "host": event_block.get("job-originating-host-name"),
        "notify_printer_uri": event_block.get("notify-printer-uri"),
    }
    if source_ip:
        record["source_ip"] = source_ip

    stored_record = dict(record)
    stored_record["raw_event"] = event_block
    append_webhook_event(stored_record)
    return {"ok": True, "stored_event": record}


@app.get("/api/cups/events")
def list_webhook_events(request: Request, limit: int = 50):
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Sesión no válida.")
    sanitized = max(1, limit)
    if WEBHOOK_MAX_RETURN > 0:
        sanitized = min(sanitized, WEBHOOK_MAX_RETURN)
    events = load_webhook_events(sanitized)
    return {"events": events, "limit": sanitized}


@app.get("/", response_class=HTMLResponse)
def login_page(request: Request):
    existing = get_session_user_from_request(request)
    if existing:
        return RedirectResponse(url="/dashboard", status_code=303)
    login_path = STATIC_DIR / "login.html"
    if not login_path.exists():
        raise HTTPException(status_code=500, detail="Falta login.html")
    return login_path.read_text(encoding="utf-8")


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard_page(request: Request):
    user = getattr(request.state, "user", None) or get_session_user_from_request(request)
    if not user:
        return RedirectResponse(url="/", status_code=303)
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=500, detail="Falta index.html")
    return index_path.read_text(encoding="utf-8")


@app.post("/api/auth/login")
def login(payload: LoginRequest, response: Response):
    if not BASIC_USER or not BASIC_SECRET:
        raise HTTPException(status_code=503, detail="El inicio de sesión no está configurado.")
    username = payload.username.strip()
    if not secrets.compare_digest(username, BASIC_USER):
        raise HTTPException(status_code=401, detail="Credenciales inválidas.")
    if not verify_basic_password(payload.password):
        raise HTTPException(status_code=401, detail="Credenciales inválidas.")
    token = create_session_token(username)
    set_session_cookie(response, token)
    return {"ok": True, "user": username, "expires_in": SESSION_DURATION_SECONDS}


@app.post("/api/auth/logout")
def logout(response: Response):
    clear_session_cookie(response)
    return {"ok": True}


@app.get("/api/auth/session")
def session_info(request: Request):
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Sesión no válida.")
    return {"user": user}


@app.get("/api/system/status")
def system_status():
    return {name: parse_systemctl(unit) for name, unit in SERVICE_MAP.items()}


@app.post("/api/system/{service_name}/restart")
def restart_service(service_name: str):
    unit = SERVICE_MAP.get(service_name.lower())
    if not unit:
        raise HTTPException(status_code=404, detail="Servicio desconocido")
    result = run_command([SYSTEMCTL_BIN, "restart", unit], use_sudo=True)
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=result.stderr.strip() or "No se pudo reiniciar")
    return summarize_command(result)


@app.get("/api/printers")
def list_printers():
    printers = parse_lpstat()
    return {"printers": printers, "aliases": load_printer_aliases()}


@app.post("/api/printers/clone")
def clone_printer(payload: ClonePrinterRequest):
    source = payload.source.strip()
    target = payload.target.strip()
    if source == target:
        raise HTTPException(status_code=400, detail="El origen y destino deben ser distintos")

    ppd_path = PPD_DIR / f"{source}.ppd"
    if not ppd_path.exists():
        raise HTTPException(status_code=404, detail=f"PPD de {source} no encontrado ({ppd_path})")

    create_cmd = [
        LPADMIN_BIN,
        "-p",
        target,
        "-E",
        "-v",
        payload.target_uri,
        "-D",
        payload.description or target,
        "-P",
        str(ppd_path),
    ]
    creation = run_command(create_cmd, use_sudo=True)
    if creation.returncode != 0:
        raise HTTPException(status_code=500, detail=creation.stderr.strip() or "lpadmin falló")

    options_raw = run_command([LPOPTIONS_BIN, "-p", source], use_sudo=True)
    options = extract_options(options_raw.stdout)

    applied_options: List[Dict[str, str | int]] = []
    for key, value in options.items():
        opt_cmd = [LPADMIN_BIN, "-p", target, f"-o{key}={value}"]
        res = run_command(opt_cmd, use_sudo=True)
        applied_options.append({"option": f"{key}={value}", **summarize_command(res)})

    alias_added = False
    if payload.add_alias:
        alias_added = append_printer_alias(target)

    return {
        "created": summarize_command(creation),
        "copied_options": applied_options,
        "alias_added": alias_added,
    }


@app.get("/api/logs/listener")
def listener_logs(lines: int = 120):
    log_file = latest_log_file()
    if not log_file:
        raise HTTPException(status_code=404, detail="No hay logs disponibles")
    return {
        "file": str(log_file.relative_to(BASE_DIR)),
        "lines": read_tail(log_file, max_lines=lines),
    }


@app.get("/api/stats/prints")
def print_statistics():
    return build_weekly_print_stats()


@app.get("/api/config/printers")
def printer_aliases():
    return load_printer_aliases()
