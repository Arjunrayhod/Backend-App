# CloudBus Transit System - Flask Backend API

Official production-ready REST API backend for CloudBus Transit Application, designed for deployment on Render.com.

## 🚀 Deployment on Render.com

1. **Create Web Service** on [Render Dashboard](https://dashboard.render.com/).
2. Select repository: https://github.com/Arjunrayhod/Backend-App.
3. **Environment**: Python 3
4. **Build Command**: pip install -r requirements.txt
5. **Start Command**: gunicorn app:app --workers 2 --bind 0.0.0.0:
6. **Environment Variables**:
   - SECRET_KEY: cloudbus-secret-key-render-2026
   - FLASK_ENV: production

## 📡 Endpoints
- GET / & GET /api/health - Health check & server status
- POST /api/register & POST /api/login - Authentication
- GET /api/routes - Bus routes & schedules
- POST /api/book - Booking with automatic QR & PDF pass generation
- GET /api/my-tickets - Passenger ticket history
- GET /api/verify-ticket/:ref - Conductor ticket scanner & verification
- GET /api/admin/stats & GET /api/admin/analytics - Admin reporting
