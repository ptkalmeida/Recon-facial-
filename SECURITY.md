# Security Guide - Face Recognition Pro 2.0

## Overview

This document describes the security measures implemented in Face Recognition Pro 2.0 and provides guidance for secure deployment.

## Security Features Implemented

### 1. Secure Configuration Management

**Problem Solved**: Hardcoded secrets in configuration files

**Solution**:
- All secrets moved to `.env` file (never commit this file!)
- `config.yaml` contains only non-sensitive settings
- Environment variables take precedence over file configuration
- Automatic validation of security settings on startup

**Required Environment Variables**:
```bash
# Critical - Generate strong random values
JWT_SECRET_KEY=<minimum-32-characters-random-string>
ADMIN_PASSWORD=<strong-password-min-8-chars>

# Optional with defaults
ALLOWED_ORIGINS=http://localhost:8001
RATE_LIMIT_MAX_REQUESTS=100
```

### 2. Authentication & Authorization

**Features**:
- JWT-based authentication with secure token generation
- Password strength validation (min 8 chars, uppercase, lowercase, digit, special char)
- Bcrypt password hashing (adaptive cost factor)
- Rate limiting on authentication attempts (5 attempts per 15 minutes)
- Automatic account lockout after failed attempts

**Rate Limits**:
| Endpoint | Limit | Window | Block Duration |
|----------|-------|--------|----------------|
| Login | 5 attempts | 5 minutes | 15 minutes |
| Recognition | 60 requests | 1 minute | 1 minute |
| General API | 100 requests | 1 minute | Varies |

### 3. API Security

**Implemented Protections**:
- Request size limiting (10MB default)
- Rate limiting per endpoint
- IP-based and user-based request tracking
- Suspicious request pattern detection

### 4. Security Headers

All responses include:
```
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
X-XSS-Protection: 1; mode=block
Content-Security-Policy: default-src 'self'; ...
Referrer-Policy: strict-origin-when-cross-origin
Permissions-Policy: camera=(self), microphone=(), ...
Strict-Transport-Security: max-age=31536000 (production only)
```

### 5. CORS Configuration

**Before (Insecure)**:
```python
allow_origins=["*"]  # Any origin can access
```

**After (Secure)**:
```python
# Only configured origins allowed
# Controlled via ALLOWED_ORIGINS env var
allow_origins=["http://localhost:8001", "https://yourdomain.com"]
```

### 6. Face Recognition Security

**Anti-Spoofing**:
- Liveness detection via motion analysis
- Frame difference analysis
- Replay attack prevention

**Data Protection**:
- Face embeddings stored in database (not raw images)
- L2 normalization for consistent comparison
- Quality validation before processing

## Deployment Checklist

### Production Deployment

1. **Copy and configure .env**:
   ```bash
   cp .env.example .env
   # Edit .env with secure values
   ```

2. **Generate secure secrets**:
   ```bash
   # JWT Secret (minimum 32 characters)
   openssl rand -base64 32
   
   # Encryption key
   openssl rand -base64 16
   ```

3. **Configure environment**:
   ```bash
   ENVIRONMENT=production
   ALLOWED_ORIGINS=https://yourdomain.com
   ```

4. **Disable debug features**:
   ```bash
   RELOAD=false
   ```

5. **Set strong admin password**:
   - Minimum 8 characters
   - Mix of uppercase, lowercase, numbers, and special characters
   - Avoid dictionary words

6. **Configure firewall**:
   - Restrict access to necessary ports only
   - Consider using a reverse proxy (nginx/traefik)
   - Enable TLS/SSL

7. **Set up monitoring**:
   - Enable logging to file
   - Set up log rotation
   - Monitor failed authentication attempts

## Security Best Practices

### Password Management
- Change default admin password immediately after setup
- Use password manager for strong, unique passwords
- Rotate secrets periodically
- Never commit `.env` file to version control

### Network Security
- Use HTTPS in production
- Place behind reverse proxy with TLS termination
- Restrict CORS to specific origins
- Use VPN for administrative access if possible

### Data Protection
- Regular database backups
- Encrypt backups at rest
- Limit access to database files
- Consider database encryption for sensitive deployments

### Monitoring
- Review access logs regularly
- Set up alerts for suspicious activity
- Monitor rate limiting blocks
- Check for unknown face detections

## Security Incident Response

### If You Suspect a Breach

1. **Immediately**:
   - Change admin password
   - Revoke all active sessions (restart server)
   - Review access logs

2. **Investigate**:
   - Check for unauthorized access attempts
   - Review face recognition logs
   - Verify user database integrity

3. **Recover**:
   - Restore from clean backup if necessary
   - Update all secrets
   - Review and tighten security settings

### Reporting Security Issues

If you discover a security vulnerability, please:
1. Do not create a public issue
2. Contact the maintainers directly
3. Provide detailed reproduction steps
4. Allow time for fix before disclosure

## Compliance Notes

### GDPR / Privacy Considerations
- Face embeddings are considered biometric data
- Implement data retention policies
- Provide mechanism for data deletion
- Consider data processing agreements

### Audit Trail
All security-relevant events are logged:
- Authentication attempts (success and failure)
- Password changes
- User registration/deletion
- Unknown face detections
- Access door operations

## Changelog

### Version 2.0 - Security Refactoring
- [x] Removed hardcoded secrets from config files
- [x] Implemented environment variable based configuration
- [x] Added password strength requirements
- [x] Implemented rate limiting on all critical endpoints
- [x] Added security headers to all responses
- [x] Restricted CORS configuration
- [x] Unified face recognition algorithm (DeepFace Facenet512)
- [x] Added face quality validation
- [x] Implemented anti-spoofing detection
- [x] Added request validation middleware

## References

- [OWASP Top 10](https://owasp.org/www-project-top-ten/)
- [FastAPI Security](https://fastapi.tiangolo.com/tutorial/security/)
- [DeepFace Documentation](https://github.com/serengil/deepface)
