"""Content-Security-Policy with a per-request nonce for the viewer's inline import map."""
import secrets

# Strict default for everything that is not an HTML page (static files, redirects, errors).
BASE_CSP = "default-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'"


def page_csp(nonce):
    return "; ".join([
        "default-src 'none'",
        "script-src 'self' 'nonce-%s'" % nonce,   # no 'unsafe-inline' / 'unsafe-eval'
        "style-src 'self'",
        "img-src 'self' data: blob:",
        "connect-src 'self'",                     # fetching the GLB models
        "worker-src 'self' blob:",
        "font-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "frame-ancestors 'none'",
        "form-action 'none'",
    ])


class CSPMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.csp_nonce = secrets.token_urlsafe(16)
        response = self.get_response(request)
        if response.get('Content-Type', '').startswith('text/html'):
            response['Content-Security-Policy'] = page_csp(request.csp_nonce)
        else:
            response['Content-Security-Policy'] = BASE_CSP
        return response
