# Migração server_health_checker → PulseGuard (DRF)

Este documento mapeia os módulos do projeto Python puro `server_health_checker` para a arquitetura Django/DRF multi-tenant em `pulseguard-backend`.

## Origem → Destino

- acquisition.py
  - PingCheck → `monitoring/services/check_service.py` (ICMP/TCP) e `monitoring/tasks/check_runner.py` (agendamento e persistência)
  - ServerCheck → `monitoring/services/check_service.py` (HTTP) e `monitoring/tasks/check_runner.py`
  - TimeStampCheck → novo serviço em `monitoring/services/timestamp_service.py` (a criar) com persistência em modelos próprios (se mantido)

- processor.py
  - RawReportProcessor → lógica de avaliação migra para:
    - regras simples no `check_runner.py` (thresholds) e/ou
    - agregações via endpoints de métricas em `monitoring/metrics.py`
  - Gráficos (matplotlib) → substituídos por consumo via frontend (React) com gráficos; backend expõe dados.

- dispatcher.py
  - Armazenamento SQLite ad-hoc → substituído por modelos:
    - `PingResult` (histórico de pings)
    - `ServerStatus` (estado agregado)
    - event streaming via `ServerStatusStreamView`/Channels

- sender.py
  - Notification (SMTP) → `monitoring/services/notification_service.py`
  - SMS_WhatsApp_Notification / SMS_Notification → Twilio/Textbelt opcional em `notification_service.py` (já suportado Twilio)

- configuration.py
  - settings (info.json) → configurações em DB por organização/servidor: modelos `Server`, `NotificationConfig`; variáveis sensíveis via `.env` e `core/settings/*`.

## Modelos e Multi-Tenancy

- `Server`: host, protocolo, porta, URL, organização, plano.
- `PingResult`: server FK, transmitted/received/loss/time/avg, timestamp.
- `ServerStatus`: server FK, status atual (up/down/timeout/error), response_time, atualizado.
- `NotificationConfig`: por servidor e organização, com tipos (email/sms/webhook), filtros e rate limit.

## Serviços e Tarefas

- `monitoring/services/check_service.py`: HTTP/TCP/ICMP simplificado.
- `monitoring/tasks/check_runner.py`: itera servidores ativos por organização, roda checks, persiste `PingResult` e atualiza `ServerStatus`, aciona notificações.
- `monitoring/services/notification_service.py`: SMTP, Twilio, Webhook com rate limiting.

## Endpoints

- REST: `servers`, `ping-results`, `server-status`, `notification-configs`.
- Métricas: `metrics/overview`, `metrics/uptime`, `metrics/response-times`, `metrics/failures`.
- Stream: `api/events/status/` para snapshot e atualizações.

## Itens a criar/ajustar

- `timestamp_service.py` (se mantiver funcionalidades de TimeStampCheck) + modelos correspondentes.
- Regras de thresholds (loss_rate, delays) configuráveis por organização/servidor.
- Comando de management para executar verificações sob demanda.

## Observações

- ICMP verdadeiro exige permissões; usamos fallback TCP ou biblioteca específica em produção.
- Gráficos serão responsabilidade do frontend; backend fornecerá dados agregados.
