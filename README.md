# iRoad - Administrative Dashboard

iRoad is a modern, high-security administrative dashboard built with Django 6.0 and PostgreSQL. It focuses on robust session management, role-based access control (RBAC), and comprehensive master data management (Countries, Currencies).

## 🚀 Key Features

- **Custom UUID-based User Model**: Enhanced security and scalability using UUIDs for all user identifiers.
- **Advanced Security**:
    - Brute-force protection with login attempt tracking and lockouts.
    - Immutable access logging for audit trails.
    - Two-Factor Authentication (2FA) support.
    - Configurable session timeouts.
- **Role-Based Access Control (RBAC)**: Flexible role management for permissions.
- **Master Data Management**: Centralized management for Countries and Currencies.
- **Internationalization (i18n)**: Built-in support for multiple languages (English/Arabic).

## 🛠 Tech Stack

- **Backend**: [Django 6.0.3](https://www.djangoproject.com/)
- **Database**: [PostgreSQL](https://www.postgresql.org/)
- **Environment Management**: [python-decouple](https://pypi.org/project/python-decouple/)
- **Authentication**: Custom implementation with `AbstractBaseUser`.

## 📂 Project Structure

```text
iroad/
├── config/              # Project settings and core configuration
├── superadmin/          # Main administrative application
├── static/              # Static assets (CSS, JS, Images)
├── templates/           # HTML templates
├── manage.py            # Django management script
├── .env                 # Environment configuration (not in version control)
└── req.txt              # Project dependencies
```

## ⚙️ Installation & Setup

1. **Clone the repository**:
   ```bash
   git clone <repository-url>
   cd iroad
   ```

2. **Set up a virtual environment**:
   ```bash
   python -m venv venv
   source venv/Scripts/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r req.txt
   ```

4. **Configure environment variables**:
   Create a `.env` file in the root directory and add the following:
   ```env
   SECRET_KEY=your-secret-key-here
   DEBUG=True
   DB_NAME=iroad_db
   DB_USER=your-db-user
   DB_PASSWORD=your-db-password
   DB_HOST=localhost
   DB_PORT=5432
   ALLOWED_HOSTS=127.0.0.1,localhost
   ```

5. **Apply migrations**:
   ```bash
   python manage.py migrate
   ```

6. **Seed initial data (optional)**:
   ```bash
   python seed_superadmin.py
   ```

7. **Run the development server**:
   ```bash
   python manage.py runserver
   ```

## 📜 Usage

Access the dashboard at `http://127.0.0.1:8000/`. Default administrative access can be configured through the `superadmin` module.

## 🔒 Security Notes

Access logs are designed to be **immutable** and cannot be modified or deleted through standard database operations, ensuring a reliable audit trail.
