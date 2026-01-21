# Deployment Guide - Render.com

## Quick Deploy (Automatic)

1. **Fork/Push this repo to GitHub**
2. **Go to [Render.com](https://render.com)** and sign up (free)
3. **Click "New" → "Blueprint"**
4. **Connect your GitHub repo**
5. Render will automatically detect `render.yaml` and deploy both services

## Manual Deploy

### Backend API

1. Go to Render Dashboard → "New" → "Web Service"
2. Connect your GitHub repo
3. Configure:
   - **Name**: `run-mapper-api`
   - **Environment**: `Python 3`
   - **Build Command**: `pip install poetry && poetry install`
   - **Start Command**: `poetry run uvicorn run_mapper.main:app --host 0.0.0.0 --port $PORT`
   - **Plan**: `Free`

### Frontend

1. Go to Render Dashboard → "New" → "Static Site"
2. Connect your GitHub repo
3. Configure:
   - **Name**: `run-mapper-frontend`
   - **Build Command**: `cd frontend && npm install && npm run build`
   - **Publish Directory**: `frontend/dist`
   - **Plan**: `Free`
4. Add Environment Variable:
   - **Key**: `VITE_API_BASE_URL`
   - **Value**: `https://run-mapper-api.onrender.com/api/v1` (use your actual backend URL)

## After Deployment

- Backend will be at: `https://run-mapper-api.onrender.com`
- Frontend will be at: `https://run-mapper-frontend.onrender.com`
- API docs at: `https://run-mapper-api.onrender.com/docs`

## Notes

- Free tier services sleep after 15 minutes of inactivity
- First request after sleep takes ~30 seconds to wake up
- Upgrade to paid tier ($7/month) for always-on services
