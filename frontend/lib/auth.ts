/**
 * Local authentication API client with TOTP MFA support.
 * Passwordless TOTP MFA + email magic link recovery.
 */

import { API_BASE } from "./api";

export interface User {
  id: string;
  email: string | null;
  name: string;
  preferred_language: string;
  country?: string;
  current_level: number;
  role?: string;
}

export interface RegisterRequest {
  email: string;
  name: string;
  preferred_language: string;
  country?: string;
  professional_role?: string;
}

export interface RegisterResponse {
  user_id: string;
  email: string;
  name: string;
  qr_code: string;  // Base64 encoded QR code image
  backup_codes: string[];
  secret: string;   // For manual entry
  provisioning_uri: string;
}

export interface LoginRequest {
  email: string;
  totp_code: string;  // 6-digit TOTP or 8-digit backup code
}

export interface AuthResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  user: User;
}

export interface RefreshTokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
}

export interface RegisterEmailOTPRequest {
  email: string;
  name: string;
  preferred_language: string;
  country?: string;
  professional_role?: string;
}

export interface RegisterPasswordRequest {
  identifier: string;
  password: string;
  name: string;
  preferred_language: string;
  country?: string;
  professional_role?: string;
}

export interface LoginPasswordRequest {
  identifier: string;
  password: string;
}

export interface RegisterEmailOTPResponse {
  user_id: string;
  email: string;
  name: string;
  verification_method: string;
  otp_id: string;
  expires_at: string;
  expires_in_seconds: number;
}

export interface SendLoginOTPResponse {
  otp_id: string;
  expires_at: string;
  expires_in_seconds: number;
  message: string;
}

export class AuthError extends Error {
  constructor(message: string, public status?: number) {
    super(message);
    this.name = 'AuthError';
  }
}

class AuthClient {
  private accessToken: string | null = null;
  private refreshToken: string | null = null;

  constructor() {
    // Load tokens from localStorage on initialization
    if (typeof window !== 'undefined') {
      this.accessToken = localStorage.getItem('access_token');
      this.refreshToken = localStorage.getItem('refresh_token');
    }
  }

  private async apiCall<T>(
    endpoint: string,
    options: RequestInit = {}
  ): Promise<T> {
    const url = `${API_BASE}/api/v1/auth${endpoint}`;
    
    const response = await fetch(url, {
      ...options,
      headers: {
        'Content-Type': 'application/json',
        ...options.headers,
      },
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new AuthError(
        errorData.detail || `Request failed with status ${response.status}`,
        response.status
      );
    }

    return response.json();
  }

  private async authenticatedCall<T>(
    endpoint: string,
    options: RequestInit = {}
  ): Promise<T> {
    // Add authorization header if we have an access token
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...options.headers as Record<string, string>,
    };

    if (this.accessToken) {
      headers['Authorization'] = `Bearer ${this.accessToken}`;
    }

    try {
      return await this.apiCall<T>(endpoint, {
        ...options,
        headers,
      });
    } catch (error) {
      // If we get a 401 and have a refresh token, try to refresh
      if (error instanceof AuthError && error.status === 401 && this.refreshToken) {
        try {
          await this.refreshAccessToken();
          // Retry with new token
          headers['Authorization'] = `Bearer ${this.accessToken}`;
          return await this.apiCall<T>(endpoint, {
            ...options,
            headers,
          });
        } catch {
          // Refresh failed, clear tokens and re-throw
          this.clearTokens();
          throw error;
        }
      }
      throw error;
    }
  }

  private setTokens(authResponse: AuthResponse): void {
    this.accessToken = authResponse.access_token;
    this.refreshToken = authResponse.refresh_token;

    if (typeof window !== 'undefined') {
      localStorage.setItem('access_token', authResponse.access_token);
      localStorage.setItem('refresh_token', authResponse.refresh_token);
      localStorage.setItem('user', JSON.stringify(authResponse.user));
      // Set cookie for server-side middleware auth check
      const maxAge = authResponse.expires_in || 900;
      document.cookie = `access_token=${authResponse.access_token}; path=/; max-age=${maxAge}; SameSite=Strict; Secure`;
    }
  }

  private clearTokens(): void {
    this.accessToken = null;
    this.refreshToken = null;

    if (typeof window !== 'undefined') {
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
      localStorage.removeItem('user');
      // Clear middleware auth cookie
      document.cookie = 'access_token=; path=/; max-age=0; SameSite=Strict; Secure';
    }
  }

  /**
   * Register a new user and initiate TOTP setup
   */
  async register(request: RegisterRequest): Promise<RegisterResponse> {
    return this.apiCall<RegisterResponse>('/register', {
      method: 'POST',
      body: JSON.stringify(request),
    });
  }

  /**
   * Verify TOTP code and complete registration
   */
  async verifyTOTP(userId: string, totpCode: string): Promise<AuthResponse> {
    const response = await this.apiCall<AuthResponse>('/verify-totp', {
      method: 'POST',
      body: JSON.stringify({
        user_id: userId,
        totp_code: totpCode,
      }),
    });

    this.setTokens(response);
    return response;
  }

  /**
   * Login with email and TOTP code
   */
  async login(request: LoginRequest): Promise<AuthResponse> {
    const response = await this.apiCall<AuthResponse>('/login', {
      method: 'POST',
      body: JSON.stringify(request),
    });

    this.setTokens(response);
    return response;
  }

  /**
   * Send magic link for account recovery
   */
  async sendMagicLink(email: string): Promise<{ message: string }> {
    return this.apiCall<{ message: string }>('/magic-link', {
      method: 'POST',
      body: JSON.stringify({ email }),
    });
  }

  /**
   * Verify magic link and get new TOTP setup
   */
  async verifyMagicLink(token: string): Promise<RegisterResponse> {
    return this.apiCall<RegisterResponse>('/verify-magic-link', {
      method: 'POST',
      body: JSON.stringify({ token }),
    });
  }

  /**
   * Refresh access token using refresh token
   */
  async refreshAccessToken(): Promise<void> {
    if (!this.refreshToken) {
      throw new AuthError('No refresh token available');
    }

    const response = await this.apiCall<RefreshTokenResponse>('/refresh', {
      method: 'POST',
      body: JSON.stringify({
        refresh_token: this.refreshToken,
      }),
    });

    this.accessToken = response.access_token;
    if (typeof window !== 'undefined') {
      localStorage.setItem('access_token', response.access_token);
      // Update middleware auth cookie
      const maxAge = response.expires_in || 900;
      document.cookie = `access_token=${response.access_token}; path=/; max-age=${maxAge}; SameSite=Strict; Secure`;
    }
  }

  /**
   * Logout user and clear tokens
   */
  async logout(): Promise<void> {
    if (this.refreshToken) {
      try {
        await this.apiCall('/logout', {
          method: 'POST',
          body: JSON.stringify({
            refresh_token: this.refreshToken,
          }),
        });
      } catch (error) {
        // Don't throw on logout errors, just clear tokens
        console.warn('Logout request failed:', error);
      }
    }

    this.clearTokens();
  }

  /**
   * Get current user from localStorage
   */
  getCurrentUser(): User | null {
    if (typeof window === 'undefined') return null;
    
    const userStr = localStorage.getItem('user');
    if (!userStr) return null;

    try {
      return JSON.parse(userStr);
    } catch {
      return null;
    }
  }

  /**
   * Check if user is authenticated
   */
  isAuthenticated(): boolean {
    return !!this.accessToken;
  }

  /**
   * Get current access token
   */
  getAccessToken(): string | null {
    return this.accessToken;
  }

  /**
   * Get a valid (non-expired) access token, refreshing if needed.
   * Throws AuthError if no refresh token is available or refresh fails.
   */
  async getValidToken(): Promise<string> {
    if (this.accessToken && !this.isTokenExpired(this.accessToken)) {
      return this.accessToken;
    }

    if (!this.refreshToken) {
      this.clearTokens();
      throw new AuthError('Session expired. Please log in again.', 401);
    }

    await this.refreshAccessToken();

    if (!this.accessToken) {
      this.clearTokens();
      throw new AuthError('Session expired. Please log in again.', 401);
    }

    return this.accessToken;
  }

  private isTokenExpired(token: string): boolean {
    try {
      const payload = token.split('.')[1];
      if (!payload) return true;
      const decoded = JSON.parse(atob(payload));
      if (!decoded.exp) return false;
      return decoded.exp * 1000 < Date.now() + 30_000;
    } catch {
      return true;
    }
  }

  /**
   * Make an authenticated API call to any endpoint
   */
  async authenticatedFetch<T>(
    path: string,
    options: RequestInit = {}
  ): Promise<T> {
    if (!this.accessToken && typeof window !== 'undefined') {
      this.accessToken = localStorage.getItem('access_token');
      this.refreshToken = localStorage.getItem('refresh_token');
    }

    const url = path.startsWith('/') ? `${API_BASE}${path}` : path;
    
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...options.headers as Record<string, string>,
    };

    if (this.accessToken) {
      headers['Authorization'] = `Bearer ${this.accessToken}`;
    }

    try {
      const response = await fetch(url, {
        ...options,
        headers,
      });

      if (!response.ok) {
        if (response.status === 401 && this.refreshToken) {
          // Try to refresh token
          await this.refreshAccessToken();
          headers['Authorization'] = `Bearer ${this.accessToken}`;
          
          const retryResponse = await fetch(url, {
            ...options,
            headers,
          });

          if (!retryResponse.ok) {
            const errorData = await retryResponse.json().catch(() => ({}));
            throw new AuthError(
              errorData.detail || `Request failed with status ${retryResponse.status}`,
              retryResponse.status
            );
          }

          if (retryResponse.status === 204) return undefined as T;
          return retryResponse.json();
        } else {
          const errorData = await response.json().catch(() => ({}));
          throw new AuthError(
            errorData.detail || `Request failed with status ${response.status}`,
            response.status
          );
        }
      }

      if (response.status === 204) return undefined as T;
      return response.json();
    } catch (error) {
      if (error instanceof AuthError && error.status === 401) {
        this.clearTokens();
      }
      throw error;
    }
  }

  /**
   * Register a new user and send email OTP for verification
   */
  async registerEmailOTP(request: RegisterEmailOTPRequest): Promise<RegisterEmailOTPResponse> {
    return this.apiCall<RegisterEmailOTPResponse>('/register-email-otp', {
      method: 'POST',
      body: JSON.stringify(request),
    });
  }

  /**
   * Verify email OTP code and complete registration
   */
  async verifyEmailOTP(otpId: string, otpCode: string): Promise<AuthResponse> {
    const response = await this.apiCall<AuthResponse>('/verify-email-otp', {
      method: 'POST',
      body: JSON.stringify({
        otp_id: otpId,
        otp_code: otpCode,
      }),
    });

    this.setTokens(response);
    return response;
  }

  /**
   * Send OTP for email-based login
   */
  async sendLoginOTP(email: string): Promise<SendLoginOTPResponse> {
    return this.apiCall<SendLoginOTPResponse>('/send-login-otp', {
      method: 'POST',
      body: JSON.stringify({ email }),
    });
  }

  /**
   * Verify login OTP code and authenticate user
   */
  async verifyLoginOTP(otpId: string, otpCode: string): Promise<AuthResponse> {
    const response = await this.apiCall<AuthResponse>('/verify-login-otp', {
      method: 'POST',
      body: JSON.stringify({
        otp_id: otpId,
        otp_code: otpCode,
      }),
    });

    this.setTokens(response);
    return response;
  }

  /**
   * Register a new user with email/phone + password
   */
  async registerPassword(request: RegisterPasswordRequest): Promise<AuthResponse> {
    const response = await this.apiCall<AuthResponse>('/register-password', {
      method: 'POST',
      body: JSON.stringify(request),
    });

    this.setTokens(response);
    return response;
  }

  /**
   * Login with email/phone + password
   */
  async loginPassword(request: LoginPasswordRequest): Promise<AuthResponse> {
    const response = await this.apiCall<AuthResponse>('/login-password', {
      method: 'POST',
      body: JSON.stringify(request),
    });

    this.setTokens(response);
    return response;
  }

  /**
   * Request a password reset link
   */
  async requestPasswordReset(identifier: string): Promise<{ message: string }> {
    return this.apiCall<{ message: string }>('/request-password-reset', {
      method: 'POST',
      body: JSON.stringify({ identifier }),
    });
  }

  /**
   * Reset password using token from reset link
   */
  async resetPassword(token: string, newPassword: string): Promise<{ message: string }> {
    return this.apiCall<{ message: string }>('/reset-password', {
      method: 'POST',
      body: JSON.stringify({ token, new_password: newPassword }),
    });
  }
}

// Export singleton instance
export const authClient = new AuthClient();