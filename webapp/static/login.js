const loginForm = document.getElementById('login-form');
const loginErrorEl = document.getElementById('login-error');
const loginSubmit = document.getElementById('login-submit');
const toastEl = document.getElementById('toast');

function showToast(message, type = 'info') {
  if (!toastEl) return;
  toastEl.textContent = message;
  toastEl.dataset.type = type;
  toastEl.hidden = false;
  clearTimeout(showToast.timeoutId);
  showToast.timeoutId = setTimeout(() => {
    toastEl.hidden = true;
  }, 4000);
}

if (loginForm) {
  loginForm.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (loginErrorEl) loginErrorEl.hidden = true;
    const formData = new FormData(loginForm);
    const payload = {
      username: formData.get('username'),
      password: formData.get('password'),
    };
    if (loginSubmit) {
      loginSubmit.disabled = true;
      loginSubmit.textContent = 'Ingresando…';
    }
    try {
      const response = await fetch('/api/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        const detail = data.detail || response.statusText || 'Credenciales inválidas';
        throw new Error(detail);
      }
      showToast('Sesión iniciada, redirigiendo...');
      window.location.href = '/dashboard';
    } catch (err) {
      if (loginErrorEl) {
        loginErrorEl.textContent = err.message || 'No se pudo iniciar sesión.';
        loginErrorEl.hidden = false;
      }
    } finally {
      if (loginSubmit) {
        loginSubmit.disabled = false;
        loginSubmit.textContent = 'Iniciar sesión';
      }
    }
  });

  loginForm.addEventListener('input', () => {
    if (loginErrorEl) loginErrorEl.hidden = true;
  });
}
