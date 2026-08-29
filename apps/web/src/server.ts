import {
  AngularNodeAppEngine,
  createNodeRequestHandler,
  isMainModule,
  writeResponseToNodeResponse,
} from '@angular/ssr/node';
import express from 'express';
import { request as httpRequest } from 'node:http';
import { join } from 'node:path';

const browserDistFolder = join(import.meta.dirname, '../browser');

const app = express();
const angularApp = new AngularNodeAppEngine();

const apiHost = process.env['AUREX_API_HOST'] || '127.0.0.1';
const apiPort = Number(process.env['AUREX_API_PORT'] || 8010);

app.get('/_health', (_req, res) => {
  res.status(200).json({ status: 'healthy', service: 'aurex-web' });
});

/** Keep production browser traffic same-origin while FastAPI stays localhost-only. */
app.use(['/api', '/health'], (req, res) => {
  const headers = { ...req.headers, host: `${apiHost}:${apiPort}` };
  const upstream = httpRequest(
    {
      hostname: apiHost,
      port: apiPort,
      method: req.method,
      path: req.originalUrl,
      headers,
    },
    (upstreamResponse) => {
      res.status(upstreamResponse.statusCode ?? 502);
      for (const [name, value] of Object.entries(upstreamResponse.headers)) {
        if (value !== undefined) res.setHeader(name, value);
      }
      upstreamResponse.pipe(res);
    },
  );
  upstream.setTimeout(30_000, () => upstream.destroy(new Error('API proxy timeout')));
  upstream.on('error', () => {
    if (!res.headersSent) {
      res.status(502).json({ status: 'unavailable', message: 'Aurex API is unavailable' });
    } else {
      res.end();
    }
  });
  req.pipe(upstream);
});

/**
 * Example Express Rest API endpoints can be defined here.
 * Uncomment and define endpoints as necessary.
 *
 * Example:
 * ```ts
 * app.get('/api/{*splat}', (req, res) => {
 *   // Handle API request
 * });
 * ```
 */

/**
 * Serve static files from /browser
 */
app.use(
  express.static(browserDistFolder, {
    maxAge: '1y',
    index: false,
    redirect: false,
  }),
);

/**
 * Handle all other requests by rendering the Angular application.
 */
app.use((req, res, next) => {
  angularApp
    .handle(req)
    .then((response) =>
      response ? writeResponseToNodeResponse(response, res) : next(),
    )
    .catch(next);
});

/**
 * Start the server if this module is the main entry point, or it is ran via PM2.
 * The server listens on the port defined by the `PORT` environment variable, or defaults to 4000.
 */
if (isMainModule(import.meta.url) || process.env['pm_id']) {
  const port = process.env['PORT'] || 4000;
  const host = process.env['HOST'] || '127.0.0.1';
  app.listen(Number(port), host, (error) => {
    if (error) {
      throw error;
    }

    console.log(`Aurex web listening on http://${host}:${port}`);
  });
}

/**
 * Request handler used by the Angular CLI (for dev-server and during build) or Firebase Cloud Functions.
 */
export const reqHandler = createNodeRequestHandler(app);
