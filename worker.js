/**
 * worker.js – Cloudflare Worker entry-point for CryptoInfo
 *
 * This thin Worker receives all inbound HTTP requests and forwards them to the
 * Flask/Gunicorn server running inside the Cloudflare Container.
 *
 * How it works
 * ────────────
 * Cloudflare Containers are built on top of Durable Objects.  The
 * `CryptoinfoApp` class exported below extends the built-in `Container` class,
 * which handles starting the Docker image, routing TCP traffic to the
 * container's port 8080, and hibernating the container after the configured
 * idle timeout.
 *
 * The default fetch handler gets (or lazily creates) the single container
 * instance via `idFromName("singleton")` and delegates the request to it.
 * Replace "singleton" with a per-user or per-session key if you ever need
 * isolated container instances.
 *
 * Deployment
 * ──────────
 * 1. Build and push the image:
 *      docker build -t cryptoinfo .
 *      wrangler containers push cryptoinfo
 * 2. Deploy the Worker + container binding:
 *      wrangler deploy
 *
 * Ref: https://developers.cloudflare.com/containers/
 */

import { Container } from "cloudflare:containers";

/**
 * CryptoinfoApp – Cloudflare Container class.
 *
 * Cloudflare automatically starts the Docker image specified in wrangler.toml
 * when the first request arrives, forwards HTTP traffic to port 8080 (where
 * Gunicorn listens), and hibernates the container after `sleepAfter` of
 * inactivity to minimise costs.
 */
export class CryptoinfoApp extends Container {
  /** Port that Gunicorn binds inside the container (see Dockerfile / CMD). */
  defaultPort = 8080;

  /** Hibernate the container after 5 minutes of idle traffic. */
  sleepAfter = "5m";
}

export default {
  /**
   * Route every incoming request to the single container instance.
   *
   * @param {Request} request – The incoming HTTP request.
   * @param {object}  env     – Worker environment bindings (see wrangler.toml).
   * @returns {Promise<Response>}
   */
  async fetch(request, env) {
    const containerId = env.CryptoinfoApp.idFromName("singleton");
    const containerStub = env.CryptoinfoApp.get(containerId);
    return containerStub.fetch(request);
  },
};
