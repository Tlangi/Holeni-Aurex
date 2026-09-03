import { ApplicationConfig, provideBrowserGlobalErrorListeners } from '@angular/core';
import { provideRouter } from '@angular/router';

import { routes } from './app.routes';
import { provideClientHydration, withEventReplay } from '@angular/platform-browser';
import { HttpInterceptorFn, provideHttpClient, withFetch, withInterceptors } from '@angular/common/http';

const csrfInterceptor: HttpInterceptorFn = (request, next) => {
  if (!['POST', 'PUT', 'PATCH', 'DELETE'].includes(request.method)) return next(request);
  const token = document.cookie.split('; ').find((item) => item.startsWith('aurex_csrf='))?.split('=')[1];
  return next(token ? request.clone({ setHeaders: { 'X-Aurex-CSRF': decodeURIComponent(token) } }) : request);
};

export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideRouter(routes),
    provideClientHydration(withEventReplay()),
    provideHttpClient(withFetch(), withInterceptors([csrfInterceptor]))
  ]
};
