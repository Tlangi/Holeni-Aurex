import { Routes } from '@angular/router';
import { DashboardComponent } from './app';
import { ownerGuard } from './auth.guard';

export const routes: Routes = [
  { path: 'login', loadComponent: () => import('./login').then((module) => module.LoginComponent) },
  {
    path: 'research/advanced',
    loadComponent: () => import('./research').then((module) => module.ResearchComponent),
    canActivate: [ownerGuard],
  },
  {
    path: 'experimental-lab',
    loadComponent: () => import('./experimental-lab').then((module) => module.ExperimentalLabComponent),
    canActivate: [ownerGuard],
  },
  { path: 'dashboard', component: DashboardComponent, canActivate: [ownerGuard] },
  { path: 'markets', component: DashboardComponent, canActivate: [ownerGuard] },
  { path: 'markets/:market', component: DashboardComponent, canActivate: [ownerGuard] },
  { path: 'trading', component: DashboardComponent, canActivate: [ownerGuard] },
  { path: 'research', component: DashboardComponent, canActivate: [ownerGuard] },
  { path: 'risk', component: DashboardComponent, canActivate: [ownerGuard] },
  { path: 'system', component: DashboardComponent, canActivate: [ownerGuard] },
  { path: '', redirectTo: 'dashboard', pathMatch: 'full' },
  { path: '**', redirectTo: 'dashboard' },
];
