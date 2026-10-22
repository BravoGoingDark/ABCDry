# ============================================================================
# USER AUTHENTICATION & ACTIVITY TRACKING GUIDE
# ABCDryBASiN Agricultural Metrics Dashboard
# ============================================================================

## OVERVIEW

The database now captures **comprehensive user tracking** across the entire application:
- **Login attempts** (success/failure, timestamps, IP addresses)
- **User sessions** (active sessions, duration, activity timeline)
- **User activity log** (all actions: page views, data imports, exports, configurations)
- **Audit logs** (data changes with who, what, when)

---

## DATABASE TABLES ADDED

### 1. LOGIN_ATTEMPTS (Compliance & Security)
**Purpose:** Track all login attempts for security auditing

**Fields:**
```sql
attempt_id      BIGSERIAL (unique ID)
username        VARCHAR(255) - Username or email
status          VARCHAR(50) - success, failed_wrong_password, user_not_found, account_locked, mfa_required, mfa_failed
ip_address      INET - Source IP address
user_agent      TEXT - Browser/client information
attempted_at    TIMESTAMP - When the login attempt occurred
session_id      VARCHAR(255) - Session ID if successful
error_message   TEXT - Why login failed (optional)
```

**Indexed By:**
- `username, attempted_at DESC` - Find all attempts by username
- `ip_address, attempted_at DESC` - Detect brute force from IP
- `attempted_at DESC WHERE status != 'success'` - Find failed logins

**Retention Policy:** Manual cleanup (recommend 90 days)

**Use Cases:**
- Security audit: Who logged in and when?
- Brute force detection: Multiple failed logins from same IP
- Compliance reporting: Login history for a user
- Incident investigation: What happened at specific time?

---

### 2. USER_SESSIONS (Session Management)
**Purpose:** Track active and historical user sessions

**Fields:**
```sql
session_id            VARCHAR(255) PRIMARY KEY - Unique session identifier
user_id               BIGINT - Django auth_user ID
username              VARCHAR(255) - Username for quick lookup
login_time            TIMESTAMP - When user logged in
last_activity         TIMESTAMP - Last recorded activity
logout_time           TIMESTAMP - When user logged out (NULL if still active)
ip_address            INET - Source IP address
user_agent            TEXT - Browser information
is_active             BOOLEAN - Is this session still active?
session_duration_minutes INTEGER - Total session time
```

**Indexed By:**
- `user_id, is_active WHERE is_active = TRUE` - Find active sessions for user
- `login_time DESC, logout_time` - Session timeline

**Integration:**
- Works with Django's session backend
- Can replace default session table with this for better tracking

**Use Cases:**
- Find all active sessions for a user (kick out duplicates)
- Session timeout management
- Concurrent session limit enforcement
- User activity timeline

---

### 3. USER_ACTIVITY_LOG (Time-Series Activity Tracking)
**Purpose:** TimescaleDB hypertable capturing every user action

**Key Feature:** This is a **hypertable** - optimized for high-volume time-series data with automatic compression

**Fields:**
```sql
activity_id      BIGSERIAL - Unique ID
user_id          BIGINT - Who performed the action
time             TIMESTAMP - When action occurred (time dimension for hypertable)
session_id       VARCHAR(255) - Which session
action           VARCHAR(100) - page_view, data_export, data_import, config_change, report_generated, etc
resource_type    VARCHAR(100) - dashboard, analysis, data_ingestion, settings, admin, etc
resource_name    VARCHAR(255) - Specific page/report name
details          JSONB - Context data (parameters, filters, record counts, results, etc)
ip_address       INET - Source IP (may differ from session if VPN/proxy)
status           VARCHAR(20) - success or failure
response_time_ms INTEGER - How long the action took
```

**Indexed By:**
- `user_id, time DESC` - All activities by user
- `resource_type, time DESC` - Track usage patterns (which features used)
- `session_id, time DESC` - Activities during specific session

**Compression Policy:** Automatically compressed after 90 days (saves 80% space)

**Retention Policy:** Automatically deleted after 1 year (configurable)

**Storage:** With 1000 users logging 100 actions/day = 100K records/day
- Raw: ~50MB/day → Compressed (90+ days old): ~10MB/day
- 1 year = ~18GB raw → ~3.6GB compressed

**Use Cases:**
- Audit trail: What did user do and when?
- Usage analytics: Which features are used most?
- Performance monitoring: Slow response times
- Troubleshooting: Reproduce user's actions
- Fraud detection: Unusual activity patterns
- Compliance reporting: User action history

---

### 4. AUDIT_LOGS (Data Change Auditing)
**Enhanced with indexes for better performance**

**Now tracks:**
- Who changed data (user_id)
- What table was modified (table_name)
- Which record (record_id)
- What action (INSERT, UPDATE, DELETE)
- Old values (JSONB before change)
- New values (JSONB after change)
- When (change_timestamp)
- From where (ip_address)

**Indexed By:**
- `table_name, record_id, change_timestamp DESC` - Track history of specific record
- `user_id, change_timestamp DESC` - Track all changes by user

---

## IMPLEMENTATION IN DJANGO

### 1. Create Django Models

```python
# dashboard/models.py (add to existing models)

from django.contrib.auth.models import User
from django.db import models

class LoginAttempt(models.Model):
    STATUS_CHOICES = [
        ('success', 'Successful Login'),
        ('failed_wrong_password', 'Wrong Password'),
        ('user_not_found', 'User Not Found'),
        ('account_locked', 'Account Locked'),
        ('mfa_required', 'MFA Required'),
        ('mfa_failed', 'MFA Failed'),
    ]
    
    username = models.CharField(max_length=255, db_index=True)
    status = models.CharField(max_length=50, choices=STATUS_CHOICES)
    ip_address = models.GenericIPAddressField(db_index=True)
    user_agent = models.TextField()
    attempted_at = models.DateTimeField(auto_now_add=True, db_index=True)
    session_id = models.CharField(max_length=255, null=True, blank=True)
    error_message = models.TextField(blank=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['username', '-attempted_at']),
            models.Index(fields=['ip_address', '-attempted_at']),
        ]
        ordering = ['-attempted_at']
    
    def __str__(self):
        return f"{self.username} - {self.status} - {self.attempted_at}"


class UserSession(models.Model):
    session_id = models.CharField(max_length=255, primary_key=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sessions')
    login_time = models.DateTimeField(auto_now_add=True)
    last_activity = models.DateTimeField(auto_now=True)
    logout_time = models.DateTimeField(null=True, blank=True)
    ip_address = models.GenericIPAddressField()
    user_agent = models.TextField()
    is_active = models.BooleanField(default=True, db_index=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['user_id', 'is_active']),
        ]
    
    def __str__(self):
        return f"{self.user.username} - {self.login_time}"


class UserActivityLog(models.Model):
    ACTION_CHOICES = [
        ('page_view', 'Page View'),
        ('data_export', 'Data Export'),
        ('data_import', 'Data Import'),
        ('config_change', 'Configuration Change'),
        ('report_generated', 'Report Generated'),
        ('alert_triggered', 'Alert Triggered'),
    ]
    
    RESOURCE_CHOICES = [
        ('dashboard', 'Dashboard'),
        ('analysis', 'Analysis'),
        ('data_ingestion', 'Data Ingestion'),
        ('metrics', 'Metrics'),
        ('settings', 'Settings'),
        ('admin', 'Admin Panel'),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='activities')
    time = models.DateTimeField(auto_now_add=True, db_index=True)
    session = models.ForeignKey(UserSession, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=100, choices=ACTION_CHOICES)
    resource_type = models.CharField(max_length=100, choices=RESOURCE_CHOICES)
    resource_name = models.CharField(max_length=255)
    details = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField()
    status = models.CharField(max_length=20, default='success')
    response_time_ms = models.IntegerField(null=True, blank=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['user_id', '-time']),
            models.Index(fields=['resource_type', '-time']),
        ]
        ordering = ['-time']
    
    def __str__(self):
        return f"{self.user.username} - {self.action} - {self.time}"
```

### 2. Create Custom Authentication Backend

```python
# dashboard/auth.py

from django.contrib.auth import authenticate
from django.contrib.auth.backends import ModelBackend
from dashboard.models import LoginAttempt, UserSession
import uuid
from django.utils import timezone

class TrackingAuthenticationBackend(ModelBackend):
    """Custom backend that logs all login attempts"""
    
    def authenticate(self, request, username=None, password=None, **kwargs):
        """Authenticate and log attempt"""
        
        ip_address = get_client_ip(request)
        user_agent = request.META.get('HTTP_USER_AGENT', '')
        
        try:
            # Try Django's default authentication
            user = super().authenticate(request, username=username, password=password, **kwargs)
            
            if user is not None:
                # Successful login
                session_id = str(uuid.uuid4())
                
                LoginAttempt.objects.create(
                    username=username,
                    status='success',
                    ip_address=ip_address,
                    user_agent=user_agent,
                    session_id=session_id
                )
                
                # Create session record
                UserSession.objects.create(
                    session_id=session_id,
                    user=user,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    is_active=True
                )
                
                return user
            else:
                # Failed login
                try:
                    from django.contrib.auth.models import User
                    User.objects.get(username=username)
                    status = 'failed_wrong_password'
                except User.DoesNotExist:
                    status = 'user_not_found'
                
                LoginAttempt.objects.create(
                    username=username,
                    status=status,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    error_message='Invalid credentials'
                )
                
                return None
        
        except Exception as e:
            LoginAttempt.objects.create(
                username=username or 'unknown',
                status='failed_wrong_password',
                ip_address=ip_address,
                user_agent=user_agent,
                error_message=str(e)
            )
            return None


def get_client_ip(request):
    """Get client IP from request"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip
```

### 3. Activity Logging Middleware

```python
# dashboard/middleware.py

from django.utils.deprecation import MiddlewareMixin
from dashboard.models import UserActivityLog
from dashboard.auth import get_client_ip
import time
import json

class UserActivityLoggingMiddleware(MiddlewareMixin):
    """Log all user activities"""
    
    def process_request(self, request):
        request._start_time = time.time()
    
    def process_response(self, request, response):
        # Only log for authenticated users
        if not request.user.is_authenticated:
            return response
        
        # Skip admin/static/media
        if request.path.startswith(('/admin/', '/static/', '/media/')):
            return response
        
        # Calculate response time
        response_time_ms = int((time.time() - getattr(request, '_start_time', time.time())) * 1000)
        
        # Determine action and resource
        action = 'page_view'
        resource_type = 'dashboard'
        resource_name = request.path
        
        if request.method == 'POST':
            if 'import' in request.path.lower():
                action = 'data_import'
            elif 'export' in request.path.lower():
                action = 'data_export'
            else:
                action = 'config_change'
        
        # Determine resource type from path
        if 'analysis' in request.path:
            resource_type = 'analysis'
        elif 'data_ingestion' in request.path or 'import' in request.path:
            resource_type = 'data_ingestion'
        elif 'admin' in request.path:
            resource_type = 'admin'
        elif 'metrics' in request.path:
            resource_type = 'metrics'
        elif 'settings' in request.path:
            resource_type = 'settings'
        
        # Log activity
        UserActivityLog.objects.create(
            user=request.user,
            action=action,
            resource_type=resource_type,
            resource_name=resource_name,
            details={
                'method': request.method,
                'status_code': response.status_code,
                'path': request.path,
                'query_params': dict(request.GET),
            },
            ip_address=get_client_ip(request),
            status='success' if response.status_code < 400 else 'failure',
            response_time_ms=response_time_ms
        )
        
        return response
```

### 4. Add to Django Settings

```python
# settings_production.py

AUTHENTICATION_BACKENDS = [
    'dashboard.auth.TrackingAuthenticationBackend',
    'django.contrib.auth.backends.ModelBackend',  # Fallback
]

MIDDLEWARE = [
    # ... other middleware ...
    'dashboard.middleware.UserActivityLoggingMiddleware',  # Add this
    # ... other middleware ...
]

# Add models to INSTALLED_APPS if not already there
INSTALLED_APPS = [
    # ... other apps ...
    'dashboard',
]
```

---

## QUERIES FOR ANALYSIS

### 1. Find Failed Login Attempts (Security)

```sql
SELECT 
    username,
    COUNT(*) as failed_attempts,
    MAX(attempted_at) as last_attempt,
    array_agg(DISTINCT ip_address) as from_ips
FROM login_attempts
WHERE status != 'success'
    AND attempted_at > NOW() - INTERVAL '24 hours'
GROUP BY username
HAVING COUNT(*) > 3  -- More than 3 failures in 24 hours
ORDER BY failed_attempts DESC;
```

### 2. User Activity Timeline

```sql
SELECT 
    action,
    resource_type,
    COUNT(*) as count,
    AVG(response_time_ms) as avg_response_ms,
    MAX(response_time_ms) as max_response_ms
FROM user_activity_log
WHERE user_id = 1  -- Replace with actual user ID
    AND time > NOW() - INTERVAL '7 days'
GROUP BY action, resource_type
ORDER BY count DESC;
```

### 3. Which Features Are Used Most?

```sql
SELECT 
    resource_type,
    COUNT(*) as total_uses,
    COUNT(DISTINCT user_id) as unique_users,
    AVG(response_time_ms) as avg_response_ms
FROM user_activity_log
WHERE time > NOW() - INTERVAL '30 days'
GROUP BY resource_type
ORDER BY total_uses DESC;
```

### 4. Slow Pages/Features

```sql
SELECT 
    resource_name,
    AVG(response_time_ms) as avg_response_ms,
    MAX(response_time_ms) as max_response_ms,
    COUNT(*) as requests
FROM user_activity_log
WHERE time > NOW() - INTERVAL '7 days'
GROUP BY resource_name
HAVING AVG(response_time_ms) > 1000  -- Slower than 1 second
ORDER BY avg_response_ms DESC;
```

### 5. Data Audit Trail (Who Changed What)

```sql
SELECT 
    audit_logs.change_timestamp,
    audit_logs.user_id,
    audit_logs.table_name,
    audit_logs.record_id,
    audit_logs.action,
    audit_logs.old_values,
    audit_logs.new_values
FROM audit_logs
WHERE table_name = 'dashboard_climametrics'
    AND record_id = 123  -- Replace with actual record ID
ORDER BY change_timestamp DESC;
```

### 6. Active Sessions (Current)

```sql
SELECT 
    u.username,
    us.session_id,
    us.login_time,
    us.last_activity,
    us.ip_address,
    AGE(NOW(), us.login_time) as session_duration
FROM user_sessions us
JOIN auth_user u ON us.user_id = u.id
WHERE us.is_active = TRUE
ORDER BY us.last_activity DESC;
```

---

## COMPLIANCE & GDPR

### Data Retention Policies
- **Login Attempts:** 90 days (for security audit)
- **User Sessions:** 30 days after logout (session management)
- **User Activity Log:** 1 year (audit trail)
- **Audit Logs:** 2+ years (compliance requirement)

### User Data Deletion (Right to be Forgotten)
```sql
-- Delete user's personal data (GDPR Right to Erasure)
BEGIN;

-- Anonymize activity logs
UPDATE user_activity_log 
SET user_id = NULL 
WHERE user_id = 123;  -- User ID to delete

-- Anonymize login attempts
UPDATE login_attempts 
SET username = 'DELETED_USER_' || attempt_id 
WHERE username = 'user_to_delete@example.com';

-- Close any active sessions
UPDATE user_sessions 
SET is_active = FALSE, logout_time = NOW() 
WHERE user_id = 123 AND is_active = TRUE;

-- Anonymize in audit logs
UPDATE audit_logs 
SET user_id = NULL 
WHERE user_id = 123;

COMMIT;
```

---

## MONITORING & ALERTS

### Set Up Alerts
```sql
-- Alert: Multiple failed login attempts from same IP
CREATE OR REPLACE FUNCTION check_brute_force_attempts()
RETURNS TABLE(ip_address inet, failed_count bigint) AS $$
SELECT 
    ip_address,
    COUNT(*) as failed_count
FROM login_attempts
WHERE status IN ('failed_wrong_password', 'user_not_found', 'account_locked')
    AND attempted_at > NOW() - INTERVAL '1 hour'
GROUP BY ip_address
HAVING COUNT(*) > 10;
$$ LANGUAGE SQL;

-- Check for brute force
SELECT * FROM check_brute_force_attempts();
```

---

## MIGRATION STEPS

1. **Update database schema:** Already done! (added 3 new tables + indexes)

2. **Create Django models:** Use code above

3. **Create migrations:**
   ```bash
   python manage.py makemigrations
   python manage.py migrate
   ```

4. **Update settings:**
   ```bash
   # Edit settings_production.py with AUTHENTICATION_BACKENDS and MIDDLEWARE
   ```

5. **Test:**
   ```bash
   python manage.py runserver
   # Try login and check if activities are being logged
   psql -d agri_db -c "SELECT * FROM login_attempts ORDER BY attempted_at DESC LIMIT 5;"
   ```

---

## SUMMARY

✅ **Login Tracking:** All authentication attempts captured  
✅ **Session Management:** Track active users and session duration  
✅ **Activity Logging:** Every user action recorded with timestamp  
✅ **Audit Trail:** All data changes tracked with who/what/when  
✅ **Compliance:** 1+ year retention, GDPR-ready  
✅ **Performance:** Time-series hypertable with compression  
✅ **Security:** IP tracking, failed login monitoring  

Now your application has **complete visibility** into what every user does, from login to data modifications.

