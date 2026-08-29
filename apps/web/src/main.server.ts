import { BootstrapContext, bootstrapApplication } from '@angular/platform-browser';
import { App } from './app/root';
import { config } from './app/app.config.server';

const bootstrap = (context: BootstrapContext) =>
    bootstrapApplication(App, config, context);

export default bootstrap;
