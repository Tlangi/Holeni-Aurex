import { HttpClient } from '@angular/common/http';
import { inject, Injectable, signal } from '@angular/core';
import { Observable, tap } from 'rxjs';

export interface OwnerUser {
  id: string;
  tenant_id: string;
  email: string;
  display_name: string;
  role: string;
}

@Injectable({ providedIn: 'root' })
export class AuthApi {
  private readonly http = inject(HttpClient);
  readonly user = signal<OwnerUser | null>(null);

  me(): Observable<{ user: OwnerUser }> {
    return this.http
      .get<{ user: OwnerUser }>('/api/v1/auth/me')
      .pipe(tap((response) => this.user.set(response.user)));
  }

  login(email: string, password: string): Observable<{ user: OwnerUser }> {
    return this.http
      .post<{ user: OwnerUser }>('/api/v1/auth/login', { email, password })
      .pipe(tap((response) => this.user.set(response.user)));
  }

  logout(): Observable<{ status: string }> {
    return this.http
      .post<{ status: string }>('/api/v1/auth/logout', {})
      .pipe(tap(() => this.user.set(null)));
  }
}
