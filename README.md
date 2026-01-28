# 🔍 Site Analyzer with PDF Generation & Docker Deployment

<div align="center">

![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-green.svg)
![React](https://img.shields.io/badge/React-18+-61DAFB.svg)
![Docker](https://img.shields.io/badge/Docker-24.0+-blue.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)

**Advanced web analytics platform with AI-powered site analysis and PDF report generation**

[Live Demo](http://185.117.155.237) • [Documentation](#features) • [Getting Started](#-installation)

</div>

---

## ✨ Features

### 🎯 Core Functionality

- **🤖 AI-Powered Site Analysis**
  - Advanced LLM-powered website content analysis
  - Targeted advertising strategy generation
  - Competitor insights and market positioning
  - Structured JSON-based analysis results

- **📊 PDF Report Generation**
  - Professional multi-page PDF reports with Cyrillic support
  - Interactive detailed analysis exports
  - Customizable branding and formatting
  - html2canvas + jsPDF integration

- **👥 User Management**
  - Secure JWT-based authentication
  - Role-based access control (Admin, User, Frontend Dev)
  - Admin panel for user management
  - Registration controlled by administrator

- **📈 Analysis History**
  - Complete request/audit log
  - Site analysis history with timestamps
  - Export and review previous results

### 🚀 Deployment & Infrastructure

- **🐳 Docker Compose Orchestration**
  - Containerized frontend and backend
  - Production-ready multi-stage builds
  - Automated health checks

- **🔄 Auto-Update System**
  - Cron-based hourly container updates
  - Docker Hub integration
  - Automated deployment scripts
  - Zero-downtime updates

- **🌐 Production Setup**
  - Nginx reverse proxy configuration
  - SSL-ready infrastructure
  - Optimized timeout settings for LLM operations
  - Comprehensive logging system

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                         Frontend (React)                     │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  Login Form │ Dashboard │ Admin Panel │ History Panel │  │
│  └────────────────────────────────────────────────────────┘  │
└────────────────────┬────────────────────────────────────────┘
                     │ HTTP/HTTPS
                     ▼
┌─────────────────────────────────────────────────────────────┐
│                      Nginx Reverse Proxy                     │
│         (API Proxy / Static Files / SSL Support)            │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│                      Backend (FastAPI)                       │
│  ┌───────────────────┐  ┌──────────────────┐  ┌───────────┐ │
│  │   Auth Router     │  │   LLM Router     │  │  History  │ │
│  └───────────────────┘  └──────────────────┘  └───────────┘ │
│  ┌───────────────────┐  ┌──────────────────┐                 │
│  │  Admin Panel API  │  │ PDF Generator    │                 │
│  └───────────────────┘  └──────────────────┘                 │
└────────────────────┬────────────────────────────────────────┘
                     │
        ┌────────────┴────────────┐
        ▼                         ▼
┌─────────────────┐    ┌─────────────────┐
│  SQLite / DB    │    │   LLM Service    │
│  (Production:   │    │  (OpenAI API)    │
│   PostgreSQL)   │    └─────────────────┘
└─────────────────┘
```

---

## 📦 Installation

### Prerequisites

- **Python**: 3.11 or higher
- **Node.js**: 20 or higher
- **Docker**: 24.0+ (for containerized deployment)
- **Git**: Latest version

### Local Development Setup

#### Backend Setup

```bash
# Clone the repository
git clone https://github.com/mirash21/Site-Analyzer-with-PDF-generation-and-Docker-deployment.git
cd Site-Analyzer-with-PDF-generation-and-Docker-deployment

# Create virtual environment
python -m venv venv

# Activate virtual environment
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Generate secure secret key (REQUIRED for production)
python -c "import secrets; print(secrets.token_hex(32))"

# Copy example environment file
cp .env.example .env
# Edit .env with your SECRET_KEY and OPENAI_API_KEY

# Create admin user (REQUIRED on first run!)
python create_admin.py

# Start backend server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

#### Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Start development server
npm run dev

# Build for production
npm run build
```

---

## 🐳 Docker Deployment

### Quick Start (Development)

```bash
# Start all services
docker-compose up

# Run in background
docker-compose up -d

# Stop all services
docker-compose down

# View logs
docker-compose logs -f
```

### Production Deployment

```bash
# Build and push images to Docker Hub
.\build-and-push.ps1    # Windows PowerShell
# or
./build-and-push.sh     # Linux/Mac

# Deploy to remote server
.\deploy.ps1            # Windows PowerShell
# or
./deploy.sh             # Linux/Mac

# Manual production setup
docker-compose -f docker-compose.production.yml pull
docker-compose -f docker-compose.production.yml up -d
```

### Auto-Update Setup

Configure automatic hourly updates on production server:

```bash
# Setup cron job for auto-updates
./setup-cron.sh

# Or manually add to crontab:
0 * * * * /path/to/update-containers.sh >> /var/log/update-containers.log 2>&1
```

---

## 📝 Environment Configuration

Create `.env` file in the root directory:

```bash
# Security
SECRET_KEY=your-secret-key-here-generate-with-python-secrets
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# LLM Configuration
OPENAI_API_KEY=your-openai-api-key-here
OPENAI_MODEL=gpt-4o-mini

# Database (Production)
# DATABASE_URL=postgresql://user:password@host:5432/dbname
# Or use SQLite for development (default)

# CORS (Production)
# FRONTEND_URL=http://your-domain.com
```

---

## 🎯 Usage

### 1. Initial Admin Setup

```bash
python create_admin.py
```

Follow the prompts to create your admin user.

### 2. Access the Application

- **Frontend**: http://localhost:3000 (dev) or http://185.117.155.237 (production)
- **Backend API**: http://localhost:8000
- **API Documentation**: http://localhost:8000/docs

### 3. Create Users (Admin Only)

1. Login as admin
2. Navigate to Admin Panel
3. Create new users with appropriate roles

### 4. Analyze a Website

1. Login to the dashboard
2. Enter the website URL
3. Click "Analyze"
4. Wait for AI analysis (may take 30-60 seconds)
5. View results and generate PDF report

---

## 🔒 Security Best Practices

### Production Deployment Checklist

- [ ] **Change `SECRET_KEY`** - Use `python -c "import secrets; print(secrets.token_hex(32))"`
- [ ] **Configure CORS** - Set specific allowed origins instead of `*`
- [ ] **Enable HTTPS** - Use SSL/TLS certificates
- [ ] **Use Production Database** - PostgreSQL instead of SQLite
- [ ] **Set up Firewall** - Restrict access to necessary ports only
- [ ] **Regular Backups** - Implement database backup strategy
- [ ] **Monitor Logs** - Set up log aggregation and monitoring
- [ ] **Update Dependencies** - Keep packages up to date

### Password Policy

- Minimum 6 characters for admin passwords
- Bcrypt hashing with salt
- JWT token expiration set to 30 minutes

---

## 📚 API Documentation

### Authentication Endpoints

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| POST | `/auth/login` | User login | No |
| GET | `/auth/me` | Get current user info | Yes |
| POST | `/auth/register` | User registration (Admin only) | Yes (Admin) |

### Admin Endpoints

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| GET | `/auth/admin/users` | List all users | Yes (Admin) |
| POST | `/auth/admin/users` | Create new user | Yes (Admin) |
| PUT | `/auth/admin/users/{id}` | Update user | Yes (Admin) |
| DELETE | `/auth/admin/users/{id}` | Delete user | Yes (Admin) |

### LLM Analysis Endpoints

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| POST | `/llm/analyze-site` | Analyze website | Yes |
| POST | `/llm/chat` | Simple LLM query | Yes |
| POST | `/llm/chat-with-system` | Query with system prompt | Yes |
| POST | `/llm/chat-json` | Query with JSON response | Yes |

### History Endpoints

| Method | Endpoint | Description | Auth Required |
|--------|----------|-------------|---------------|
| GET | `/history/requests` | Request history | Yes |
| GET | `/history/analyses` | Site analysis history | Yes |
| GET | `/history/analysis/{id}` | Get specific analysis | Yes |

---

## 🗂️ Project Structure

```
Site-Analyzer/
├── app/
│   ├── main.py                 # FastAPI application config
│   ├── database.py             # Database configuration
│   ├── models/
│   │   └── models.py          # SQLAlchemy models
│   ├── routers/
│   │   ├── auth.py            # Authentication routes
│   │   ├── llm.py             # LLM endpoints
│   │   └── history.py         # History endpoints
│   └── services/
│       ├── auth.py            # JWT & password hashing
│       ├── logger.py          # Request logging
│       ├── llm_client.py      # OpenAI client
│       └── analyzer.py        # Site analyzer
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── LoginForm.jsx
│   │   │   ├── Dashboard.jsx
│   │   │   ├── HistoryPanel.jsx
│   │   │   ├── AdminPanel.jsx
│   │   │   ├── ResultCard.jsx
│   │   │   └── Loader.jsx
│   │   ├── utils/
│   │   │   ├── pdfGenerator.js
│   │   │   └── detailedPdfGenerator.js
│   │   ├── config.js
│   │   └── App.jsx
│   ├── nginx.conf             # Production Nginx config
│   ├── Dockerfile
│   └── package.json
├── docker-compose.yml         # Development compose
├── docker-compose.production.yml  # Production compose
├── Backend-Dockerfile
├── build-and-push.ps1         # Build & deploy scripts
├── deploy.ps1
├── update-containers.sh       # Auto-update script
├── setup-cron.sh              # Cron setup
├── create_admin.py            # Admin creation script
├── requirements.txt
└── README.md
```

---

## 🛠️ Troubleshooting

### Common Issues

**1. Login Error: "Invalid credentials"**
- Ensure admin user was created with `create_admin.py`
- Check database file exists and is writable

**2. 504 Gateway Timeout on analysis**
- Increase nginx timeout in `frontend/nginx.conf`
- Check LLM API key is valid
- Verify backend container is running

**3. PDF Generation fails**
- Ensure JavaScript is enabled
- Check browser console for errors
- Verify jsPDF and html2canvas are loaded

**4. Container won't start**
- Check Docker logs: `docker-compose logs`
- Verify ports aren't already in use
- Check environment variables in `.env`

### Log Locations

- **Backend logs**: `docker-compose logs backend-1`
- **Frontend logs**: `docker-compose logs frontend-1`
- **Update logs**: `/var/log/update-containers.log` (production)
- **Nginx logs**: Inside frontend container at `/var/log/nginx/`

---

## 🤝 Contributing

Contributions are welcome! Please follow these steps:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

---

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

---

## 👥 Authors

- **MiRash** - Initial work & Maintenance

---

## 🙏 Acknowledgments

- **OpenAI** - For the GPT API that powers site analysis
- **FastAPI** - For the excellent web framework
- **React** - For the frontend library
- **TailwindCSS** - For the UI styling
- **Docker** - For containerization support

---

## 📞 Support

For support and questions:
- 📧 Email: mirash@example.com
- 🐛 Issues: [GitHub Issues](https://github.com/mirash21/Site-Analyzer-with-PDF-generation-and-Docker-deployment/issues)
- 📚 Documentation: [Full Guide](#-documentation)

---

<div align="center">

**⭐ If you find this project useful, please consider giving it a star! ⭐**

Made with ❤️ by MiRash

</div>
