# Valluta

Django-based multiplayer leaderboard game ("võidupõund") with real-time WebSocket support.

## Tech Stack
- **Backend:** Django 6.0, Django Channels (WebSockets)
- **ASGI Server:** Daphne
- **Database:** SQLite3
- **Static Files:** WhiteNoise
- **Containerization:** Docker (Python 3.12 slim)

## Key Directories
- `/valluta` — Django project config (settings, URLs, ASGI/WSGI)
- `/game` — Core game logic: models, services, WebSocket consumers, tests, admin
- `/host` — Host interface: display, control, and API endpoints
- `/templates` — HTML templates
- `/static` — CSS, JS, images

## Common Commands
```bash
# Run dev server
python manage.py runserver

# Run migrations
python manage.py migrate

# Run tests
python manage.py test

# Production (Docker)
daphne -b 0.0.0.0 -p 8001 valluta.asgi:application
```

## URL Structure
- `/admin/` — Django admin
- `/display/` — Game display interface
- `/control/` — Game control interface
- `/api/` — API endpoints

## Environment Variables
- `DJANGO_SECRET_KEY`
- `DJANGO_DEBUG`
- `DJANGO_ALLOWED_HOSTS`
- `WHITENOISE`
