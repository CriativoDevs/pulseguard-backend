# PulseGuard Backend

Django REST Framework backend for server health monitoring system.

## Project Structure

```
pulseguard-backend/
├── core/
│   ├── settings/
│   │   ├── __init__.py          # Dynamic settings loader
│   │   ├── base.py              # Base configuration
│   │   ├── development.py       # DEV configuration
│   │   ├── staging.py           # STAGING configuration
│   │   └── production.py        # PROD configuration
│   ├── urls.py
│   ├── wsgi.py
│   └── asgi.py
├── monitoring/
│   ├── models.py                # Server, PingResult, ServerStatus, NotificationConfig
│   ├── serializers.py           # DRF Serializers
│   ├── views.py                 # ViewSets + SSE + run checks
│   ├── consumers.py             # WebSocket consumer for real-time updates
│   ├── routing.py               # WebSocket URL routing
│   ├── services/                # Business logic (health checks, notifications)
│   ├── tasks/                   # Scheduling (APScheduler) and check runner
│   ├── management/commands/     # check_servers, start_scheduler
│   ├── migrations/
│   └── admin.py
├── authentication/
│   ├── models.py
│   ├── serializers.py
│   └── views.py
├── api/
│   ├── urls.py
│   └── views.py                 # Endpoint aggregation
├── .env.dev
├── .env.stg
├── .env.prod
├── requirements.txt
└── manage.py
```

## Installation

### 1. Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate  # macOS/Linux
# or
venv\Scripts\activate  # Windows
```

### 2. Dependencies

```bash
pip install -r requirements.txt
```

### 3. Environment Variables

```bash
# For development
cp .env.dev .env
# Edit as needed
```

## Running Server

### Development

```bash
# With SQLite (default DEV)
export ENVIRONMENT=development
python manage.py migrate
python manage.py runserver
```

### Staging

```bash
export ENVIRONMENT=staging
python manage.py migrate
python manage.py runserver
```

### Production

```bash
export ENVIRONMENT=production
# Use gunicorn in production
gunicorn core.wsgi:application --bind 0.0.0.0:8000
```

## Migrations

```bash
# Create migrations after model changes
python manage.py makemigrations

# Apply migrations
python manage.py migrate

# Show migration status
python manage.py showmigrations
```

## Django Admin

```bash
python manage.py createsuperuser
python manage.py runserver
# Access: http://localhost:8000/admin
```

## Models

### Server
- Represents a monitored server
- Fields: name, protocol, host, port, path, check_interval, timeout, status, tags, notifications

### PingResult
- Result of each health check
- Fields: server, status, response_time, status_code, error_message, check_timestamp

### ServerStatus
- Current aggregated server status
- Fields: server, status, uptime_percentage, last_check, consecutive_failures, message

### NotificationConfig
- Notification configuration per server
- Types: email, webhook, sms
- Fields: server, notification_type, recipient, enabled, notify_on_failure, notify_on_recovery

## APIs

### Base URL
- DEV: `http://localhost:8000/api/`
- STAGING: `https://staging.example.com/api/`
- PROD: `https://pulseguard.example.com/api/`

### Main Endpoints
- `POST /api/auth/token/` / `refresh/` / `verify/` — JWT (SimpleJWT)
- `GET/POST /api/servers/` — Server CRUD
- `GET /api/ping-results/` — History (read-only)
- `GET /api/server-status/` — Current status (read-only)
- `GET/POST /api/notification-configs/` — Notification settings
- `POST /api/checks/run/` — Trigger checks (admin only)
- `manage.py check_servers` — Run one check pass
- `manage.py start_scheduler [--interval 300]` — Start APScheduler for periodic checks
- `GET /api/events/status/` — SSE stream of status/results
	- Optional query params: `status=up|down|degraded`, `server_id=1,2`, `since=<ISO8601>`, `limit=<int>`

### SSE (Server-Sent Events)
- Endpoint: `/api/events/status/`
- Headers: `Accept: text/event-stream`, requires JWT authentication
- Events sent:
	- `event: status` — snapshot (or delta via `since`) of `ServerStatus`
	- `event: ping` — latest `PingResult` records (limit default 50, filterable by `server_id` and `since`)
	- Heartbeat `: heartbeat` and retry hint `retry: 5000`

### WebSocket
- Endpoint: `/ws/status/`
- Requires authentication (via JWT token in connection headers)
- Closes with code 4001 if not authenticated

#### Actions (Client → Server)

**latest**: Fetch current status and recent pings from filtered servers
```json
{
  "action": "latest",
  "server_ids": [1, 2],        // optional: filter by IDs
  "query": "prod",            // optional: filter by name (icontains)
  "limit": 10                  // optional: number of recent pings (default: 20)
}
```
Response:
```json
{
  "type": "latest",
  "statuses": [                // array of ServerStatus
    {"id": 1, "server": 1, "status": "up", ...}
  ],
  "pings": [                   // array of PingResult
    {"id": 5, "server": 1, "status": "success", "response_time": 120.5, ...}
  ]
}
```

**subscribe**: Subscribe for real-time updates of specific servers
```json
{
  "action": "subscribe",
  "server_ids": [1, 2],        // optional: subscribe to these servers
  "query": "prod"             // optional: subscribe to servers matching query
}
```
Response:
```json
{
  "type": "subscribed",
  "servers": [1, 2]            // IDs of subscribed servers
}
```

#### Events (Server → Client)

**update**: Notification of new ping result after a check
```json
{
  "type": "update",
  "ping": {                    // Full PingResult
    "id": 6,
    "server": 1,
    "status": "success",
    "response_time": 115.3,
    "status_code": 200,
    "check_timestamp": "2025-12-11T16:30:00Z"
  },
  "status": {                  // Updated ServerStatus
    "id": 1,
    "server": 1,
    "status": "up",
    "uptime_percentage": 99.5,
    "last_check": "2025-12-11T16:30:00Z",
    "message": "OK"
  }
}
```

## Logging

Logs are stored in `logs/pulseguard.log` with automatic rotation every 10MB.

Log levels configurable via `.env` with `LOG_LEVEL`.

## WebSocket with Channels

### Configuration

By default, uses `InMemoryChannelLayer` for development.

For production with multiple instances, configure Redis:

```bash
# .env or export
CHANNEL_LAYER_TYPE=redis
REDIS_HOST=localhost
REDIS_PORT=6379
```

### Optional Dependencies

```bash
pip install channels-redis  # To use Redis as channel layer
```

Without this dependency, the system works with in-memory only (single process only).

## Testing

```bash
# Run all tests
python manage.py test

# Run specific app tests
python manage.py test monitoring

# Run with verbosity
python manage.py test -v 2

# Coverage report (requires coverage package)
coverage run --source='.' manage.py test
coverage report
```

## Documentation

- [Django Docs](https://docs.djangoproject.com/)
- [DRF Docs](https://www.django-rest-framework.org/)
- [Channels Docs](https://channels.readthedocs.io/)
- [APScheduler Docs](https://apscheduler.readthedocs.io/)

## Roadmap

- [x] Serializers for models
- [x] ViewSets and routing
- [x] JWT authentication
- [x] Health check service (HTTP/TCP)
- [x] Task scheduler (runner + APScheduler)
- [x] Real-time SSE (status + ping, filters, heartbeat)
- [x] Real-time WebSocket (Channels + Redis support)
- [ ] Notifications (email/SMS)
- [ ] CI/CD pipeline
- [ ] Performance monitoring and metrics
