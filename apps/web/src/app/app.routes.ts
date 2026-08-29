import { Routes } from '@angular/router';
import { DashboardComponent } from './app';
import { ownerGuard } from './auth.guard';
import { LoginComponent } from './login';
import { ResearchComponent } from './research';

export const routes: Routes = [
  { path: 'login', component: LoginComponent },
  { path: 'research', component: ResearchComponent, canActivate: [ownerGuard] },
  { path: '', component: DashboardComponent, canActivate: [ownerGuard] },
  { path: '**', redirectTo: '' },
];
