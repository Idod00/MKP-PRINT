AM_CFLAGS         = -Wall -Wcast-align 

bin_PROGRAMS      = pbmtodp
pbmtodp_SOURCES   = pbmtodp.c
pbmtodp_LDFLAGS   = 

bin_SCRIPTS       = intermec-dp-drv honeywell-dpl-drv

intermecppddir    = ${prefix}/share/cups/model/intermec
intermecppd_DATA  = ppdintermec/*.ppd

honeywellppddir    = ${prefix}/share/cups/model/honeywell
honeywellppd_DATA  = ppdhoneywell/*.ppd

ppdintermec/*.ppd:
	ppdc -d ppdintermec generic-dp_intermec.drv

ppdhoneywell/*.ppd:
	ppdc -d ppdhoneywell generic-dp_honeywell.drv
	ppdc -d ppdhoneywell generic-dp_honeywell_px940.drv
	ppdc -d ppdhoneywell generic-dpl_honeywell.drv

clean-local:
	rm ppdintermec/*
	rm ppdhoneywell/*
