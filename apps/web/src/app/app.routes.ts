import { Routes } from '@angular/router';
import { DashboardComponent } from './app';
import { ownerGuard } from './auth.guard';

export const routes: Routes = [
  { path: 'login', loadComponent: () => import('./login').then((module) => module.LoginComponent) },
  {
    path: 'research',
    loadComponent: () => import('./research').then((module) => module.ResearchComponent),
    canActivate: [ownerGuard],
  },
  {
    path: 'experimental-lab',
    loadComponent: () => import('./experimental-lab').then((module) => module.ExperimentalLabComponent),
    canActivate: [ownerGuard],
  },
  { path: '', component: DashboardComponent, canActivate: [ownerGuard] },
  { path: '**', redirectTo: '' },
];
