import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';
import { catchError, map, of } from 'rxjs';
import { AuthApi } from './auth-api';

export const ownerGuard: CanActivateFn = () => {
  const auth = inject(AuthApi);
  const router = inject(Router);
  if (auth.user()) return true;
  return auth.me().pipe(
    map(() => true),
    catchError(() => of(router.createUrlTree(['/login']))),
  );
};
