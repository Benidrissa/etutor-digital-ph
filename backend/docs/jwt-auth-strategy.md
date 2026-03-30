# JWT + Refresh Token Strategy for SantePublique AOF

## Overview

SantePublique AOF uses **Supabase Auth** as the primary authentication provider with a JWT + Refresh Token strategy. This document outlines the authentication flow, token management, and security considerations.

## Architecture

```
Frontend (Next.js) ↔ Supabase Auth ↔ Backend (FastAPI)
```

- **Supabase Auth** handles user registration, login, OAuth, and token issuance
- **Frontend** manages token storage and automatic renewal
- **Backend** validates JWT tokens for API access

## Authentication Flow

### 1. User Registration/Login

```mermaid
sequenceDiagram
    participant U as User
    participant F as Frontend
    participant S as Supabase Auth  
    participant B as Backend API

    U->>F: Register/Login
    F->>S: POST /auth/v1/token
    S->>F: JWT + Refresh Token
    F->>B: API call with Bearer token
    B->>S: Validate JWT signature
    B->>B: Extract user claims
    B->>F: API response
```

### 2. Automatic Token Refresh

```mermaid
sequenceDiagram
    participant F as Frontend
    participant S as Supabase Auth
    participant B as Backend API

    F->>B: API call (JWT expired)
    B->>F: 401 Unauthorized
    F->>S: POST /auth/v1/token (refresh_token)
    S->>F: New JWT + Refresh Token
    F->>B: Retry API call with new token
    B->>F: Success response
```

## Token Specifications

### JWT Access Token

- **Issuer**: `https://your-project.supabase.co`
- **Audience**: `authenticated`
- **Algorithm**: HS256 (HMAC SHA-256)
- **Expiry**: 1 hour (3600 seconds)
- **Size**: ~800-1200 bytes

**Claims Structure**:
```json
{
  "iss": "https://your-project.supabase.co",
  "sub": "user-uuid-here",
  "aud": "authenticated", 
  "exp": 1640995200,
  "iat": 1640991600,
  "email": "user@example.com",
  "phone": "",
  "app_metadata": {
    "provider": "email",
    "providers": ["email"]
  },
  "user_metadata": {
    "preferred_language": "fr",
    "country": "senegal", 
    "current_level": 2,
    "professional_role": "doctor"
  },
  "role": "authenticated"
}
```

### Refresh Token

- **Type**: Opaque token (random string)
- **Expiry**: 24 hours (86400 seconds) 
- **Storage**: httpOnly cookie (frontend)
- **Rotation**: New refresh token issued on each refresh
- **Size**: 43 characters (base64-encoded UUID)

## Security Implementation

### Backend JWT Validation

```python
# app/integrations/supabase_auth.py

async def verify_jwt(self, token: str) -> Dict[str, Any]:
    """Verify and decode Supabase JWT token."""
    try:
        payload = jwt.decode(
            token,
            self.jwt_secret,      # SUPABASE_JWT_SECRET
            algorithms=["HS256"],
            audience="authenticated",
            issuer=self.base_url  # SUPABASE_URL
        )
        
        # Validate expiration
        if payload.get("exp", 0) <= datetime.now(timezone.utc).timestamp():
            raise SupabaseAuthError("Token has expired")
            
        return payload
        
    except jwt.InvalidTokenError as e:
        raise SupabaseAuthError(f"Invalid token: {e}")
```

### Frontend Token Management

```typescript
// lib/supabase.ts (Next.js)

export const supabase = createClientComponentClient({
  supabaseUrl: process.env.NEXT_PUBLIC_SUPABASE_URL!,
  supabaseKey: process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
})

// Automatic token refresh handling
supabase.auth.onAuthStateChange((event, session) => {
  if (event === 'TOKEN_REFRESHED') {
    console.log('Token refreshed:', session?.access_token)
  }
  if (event === 'SIGNED_OUT') {
    // Clear local storage, redirect to login
  }
})
```

### API Request Flow

```typescript
// Frontend API calls
const { data: { session } } = await supabase.auth.getSession()

const response = await fetch('/api/v1/users/me', {
  headers: {
    'Authorization': `Bearer ${session?.access_token}`,
    'Content-Type': 'application/json'
  }
})

if (response.status === 401) {
  // Token expired - Supabase client will auto-refresh
  await supabase.auth.refreshSession()
  // Retry the request
}
```

## Environment Variables

### Backend (.env)
```bash
# Supabase Configuration
SUPABASE_URL=https://your-project-ref.supabase.co
SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9... 
SUPABASE_SERVICE_ROLE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
SUPABASE_JWT_SECRET=your-jwt-secret-key-here

# Database (Supabase provides this automatically)
DATABASE_URL=postgresql://postgres:[password]@db.[ref].supabase.co:5432/postgres
```

### Frontend (.env.local)
```bash
# Supabase Public Configuration  
NEXT_PUBLIC_SUPABASE_URL=https://your-project-ref.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

## Security Considerations

### Token Security

1. **JWT Secret Protection**
   - Never expose `SUPABASE_JWT_SECRET` to frontend
   - Rotate JWT secret periodically in production
   - Store in secure environment variables

2. **Refresh Token Storage**
   - Frontend: httpOnly cookies (secure, sameSite)
   - Never store refresh tokens in localStorage
   - Automatic rotation on each refresh

3. **Token Transmission**
   - Always use HTTPS in production  
   - Authorization header: `Bearer <jwt-token>`
   - Never include tokens in URL parameters

### Row Level Security (RLS)

PostgreSQL RLS policies enforce user data isolation:

```sql
-- Users can only see their own profile
CREATE POLICY users_isolation ON users
USING (id = current_setting('app.current_user_id')::uuid);

-- User-scoped data filtered by user_id  
CREATE POLICY user_module_progress_isolation ON user_module_progress
USING (user_id = current_setting('app.current_user_id')::uuid);
```

### Rate Limiting

- **Authentication endpoints**: 5 attempts per 15 minutes per IP
- **API endpoints**: 100 requests per minute per user
- **Tutor chat**: 50 messages per day per user
- **Password reset**: 3 attempts per hour per email

### GDPR Compliance

- **Right to erasure**: User deletion endpoint removes all personal data
- **Data minimization**: Only collect necessary profile fields
- **Consent tracking**: User metadata includes consent timestamps
- **Data portability**: Export endpoint provides user data in JSON format

## Testing Strategy

### Unit Tests
```python
# Test JWT validation
async def test_valid_jwt_token():
    auth_client = SupabaseAuthClient()
    payload = await auth_client.verify_jwt(valid_jwt)
    assert payload["sub"] == expected_user_id

async def test_expired_jwt_token():
    with pytest.raises(SupabaseAuthError):
        await auth_client.verify_jwt(expired_jwt)
```

### Integration Tests
```python
# Test protected endpoints
async def test_protected_endpoint_requires_auth():
    response = await client.get("/api/v1/users/me")
    assert response.status_code == 401

async def test_protected_endpoint_with_valid_token():
    headers = {"Authorization": f"Bearer {valid_jwt}"}
    response = await client.get("/api/v1/users/me", headers=headers)
    assert response.status_code == 200
```

## Monitoring & Observability

### Metrics to Track
- Authentication success/failure rates
- Token refresh frequency  
- Average session duration
- Failed authorization attempts per user

### Logging (structlog)
```python
logger.info(
    "User authenticated", 
    user_id=str(user.id),
    email=user.email,
    auth_provider="supabase",
    session_duration_minutes=45
)

logger.warning(
    "Authentication failed",
    error="invalid_jwt",
    ip_address="192.168.1.100",
    user_agent="Mozilla/5.0..."
)
```

## Troubleshooting

### Common Issues

1. **"Invalid JWT signature"**
   - Check `SUPABASE_JWT_SECRET` matches Supabase project
   - Verify token hasn't been modified in transit

2. **"Token has expired"**  
   - Frontend should auto-refresh tokens
   - Check system clock synchronization

3. **"User not found in database"**
   - New OAuth users need profile creation
   - Check webhook setup for user.created events

4. **RLS policy denies access**
   - Verify `current_setting('app.current_user_id')` is set
   - Check PostgreSQL logs for RLS violations

### Debug Commands

```bash
# Decode JWT payload (without verification)
echo "JWT_TOKEN_HERE" | cut -d. -f2 | base64 -d | jq

# Check Supabase project settings
curl -H "Authorization: Bearer SERVICE_ROLE_KEY" \
  https://your-project.supabase.co/rest/v1/auth/users

# Test database RLS policies
psql -c "SET app.current_user_id = 'user-uuid-here'; SELECT * FROM users;"
```

This JWT + Refresh Token strategy provides secure, scalable authentication for the SantePublique AOF platform while maintaining excellent user experience with automatic token refresh and SSO capabilities.