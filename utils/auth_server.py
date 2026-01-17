from http.server import BaseHTTPRequestHandler, HTTPServer
import urllib.parse
import threading

class AuthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed_path = urllib.parse.urlparse(self.path)
        if parsed_path.path == '/callback':
            query_params = urllib.parse.parse_qs(parsed_path.query)
            if 'code' in query_params:
                self.server.auth_code = query_params['code'][0]
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                self.wfile.write(b"<h1>Authentication successful!</h1><p>You can close this window now.</p>")
            else:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Missing code parameter.")
        else:
            self.send_response(404)
            self.end_headers()

def run_server(port=8080):
    server = HTTPServer(('localhost', port), AuthHandler)
    server.auth_code = None
    return server

def get_auth_code(port=8080):
    """
    Starts a server and waits for a single request to /callback to get the code.
    """
    server = run_server(port)
    print(f"Waiting for callback on port {port}...")
    server.handle_request() # Handles one request
    return server.auth_code
