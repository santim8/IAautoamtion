// Prueba de punta a punta de POST /status/event-to-client (int-req-mgr) sin front ni usuario real.
//
// 1. Abre el WebSocket de la plataforma con el mismo id que usa el front: {idProducto}_{tipo}_{numero}.
// 2. Envía la notificación (lo mismo que manda Bizagi).
// 3. Muestra la respuesta HTTP y el mensaje que llega por el socket.
//
// Uso (Node 22+, no requiere npm install):
//   node event_to_client.mjs --estado INVALID_USER
//   node event_to_client.mjs --estado OK --tipoAfiliacion D --doc 999000111
//   node event_to_client.mjs --estado CASE_FOR_REVIEW --paso OFFER_RESULT
//   node event_to_client.mjs --estado INVALID_USER --sin-socket   (solo valida que el estado sea aceptado)
//
// La x-api-key sale de token.txt (api_key_card_validations) o de la variable EVENT_API_KEY.

import { randomBytes } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { connect } from 'node:tls';
import { fileURLToPath } from 'node:url';

const AMBIENTES = {
  // platform-test-* apunta al backend loans-cert-back (us-east-2); dev.colsubsidio.com también lo usa.
  cert: {
    api: 'https://platform-test-internal.colsubsidio.com/loans/int-req-mgr/internal/v1/status/event-to-client',
    socket: 'wss://966rvchw1g.execute-api.us-east-2.amazonaws.com/cert',
  },
};

function argumentos(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i++) {
    if (!argv[i].startsWith('--')) continue;
    const clave = argv[i].slice(2);
    const sig = argv[i + 1];
    if (sig === undefined || sig.startsWith('--')) out[clave] = true;
    else { out[clave] = sig; i++; }
  }
  return out;
}

function apiKey() {
  if (process.env.EVENT_API_KEY) return process.env.EVENT_API_KEY;
  const raiz = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
  try {
    const linea = readFileSync(join(raiz, 'token.txt'), 'utf8').split(/\r?\n/)
      .find(l => l.startsWith('api_key_card_validations='));
    if (linea) return linea.split('=').slice(1).join('=').trim();
  } catch { /* sin token.txt */ }
  throw new Error('Falta la x-api-key: agregar api_key_card_validations=<KEY> en token.txt o exportar EVENT_API_KEY');
}

// Cliente WebSocket mínimo. No sirve el WebSocket nativo de Node: manda "sec-websocket-protocol" en
// minúsculas y la lambda on-connect lee event.headers['Sec-WebSocket-Protocol'] tal cual (responde 502).
// El navegador lo manda capitalizado, por eso al front sí le funciona.
function abrirSocket(url, protocolo) {
  const { hostname, pathname } = new URL(url);
  return new Promise((resolve, reject) => {
    const sock = connect({ host: hostname, port: 443, servername: hostname });
    const mensajes = [];
    let esperando = null;
    let buf = Buffer.alloc(0);
    let abierto = false;
    const enviarFrame = (opcode, payload = Buffer.alloc(0)) => {
      const mascara = randomBytes(4);
      const enmascarado = Buffer.from(payload.map((b, i) => b ^ mascara[i % 4]));
      sock.write(Buffer.concat([Buffer.from([0x80 | opcode, 0x80 | payload.length]), mascara, enmascarado]));
    };
    sock.on('secureConnect', () => {
      sock.write([
        `GET ${pathname} HTTP/1.1`, `Host: ${hostname}`, 'Upgrade: websocket', 'Connection: Upgrade',
        `Sec-WebSocket-Key: ${randomBytes(16).toString('base64')}`, 'Sec-WebSocket-Version: 13',
        `Sec-WebSocket-Protocol: ${protocolo}`, '', '',
      ].join('\r\n'));
    });
    sock.on('data', chunk => {
      buf = Buffer.concat([buf, chunk]);
      if (!abierto) {
        const fin = buf.indexOf('\r\n\r\n');
        if (fin < 0) return;
        const cabecera = buf.subarray(0, fin).toString();
        buf = buf.subarray(fin + 4);
        if (!cabecera.startsWith('HTTP/1.1 101')) {
          sock.destroy();
          return reject(new Error('Handshake rechazado: ' + cabecera.split('\r\n')[0]));
        }
        abierto = true;
        resolve({
          siguiente: ms => new Promise(r => {
            if (mensajes.length) return r(mensajes.shift());
            esperando = r;
            setTimeout(() => { if (esperando === r) { esperando = null; r(null); } }, ms);
          }),
          cerrar: () => { enviarFrame(0x8); sock.end(); },
        });
      }
      // Frames del servidor: sin máscara.
      while (buf.length >= 2) {
        const opcode = buf[0] & 0x0f;
        let largo = buf[1] & 0x7f, ini = 2;
        if (largo === 126) { if (buf.length < 4) return; largo = buf.readUInt16BE(2); ini = 4; }
        else if (largo === 127) { if (buf.length < 10) return; largo = Number(buf.readBigUInt64BE(2)); ini = 10; }
        if (buf.length < ini + largo) return;
        const payload = buf.subarray(ini, ini + largo);
        buf = buf.subarray(ini + largo);
        if (opcode === 0x9) enviarFrame(0xA, payload);
        else if (opcode === 0x1) {
          const texto = payload.toString('utf8');
          if (esperando) { const r = esperando; esperando = null; r(texto); } else mensajes.push(texto);
        }
      }
    });
    sock.on('error', reject);
  });
}

const a = argumentos(process.argv.slice(2));
const amb = AMBIENTES[a.env || 'cert'];
const estado = a.estado || 'INVALID_USER';
const paso = a.paso || 'VALIDATION';
const producto = String(a.producto || '2');
const tipo = a.tipo || 'CO1C';
// Documento ficticio por defecto: el endpoint no consulta el caso en Bizagi, y abrir el socket
// con el documento de alguien que esté probando en el front le cierra su conexión.
const doc = String(a.doc || '999000111');
const espera = Number(a.espera || 10) * 1000;

const body = {
  idCaso: String(a.caso || '1'),
  noveltyType: String(a.novedad || '1'),
  idProducto: producto,
  documento: { tipo, numero: doc },
  paso,
  estadoPaso: estado,
};
// En VALIDATION: con OK, datosAdicionales.tipoAfiliacion es obligatorio; con cualquier otro estado
// datosAdicionales debe ir nulo, o el servicio responde LRMGRIN (campo no válido).
if (a.tipoAfiliacion || (paso === 'VALIDATION' && estado === 'OK')) {
  body.datosAdicionales = { tipoAfiliacion: a.tipoAfiliacion || 'D' };
}

async function enviar() {
  console.log('POST', amb.api);
  console.log(JSON.stringify(body, null, 2));
  const res = await fetch(amb.api, {
    method: 'POST',
    headers: { 'content-type': 'application/json', 'x-api-key': apiKey() },
    body: JSON.stringify(body),
  });
  const texto = await res.text();
  console.log(`\nHTTP ${res.status}`);
  console.log(texto);
  let json = null;
  try { json = JSON.parse(texto); } catch { /* respuesta no JSON (WAF) */ }
  const estadoEnvio = json?.enviarEventoCliente?.estado;
  if (estadoEnvio === 'OK') console.log('=> Estado aceptado y entregado al socket.');
  else if (json?.enviarEventoCliente?.datosError?.codigoError === 'ERROR_SENDING_MESSAGE')
    console.log('=> Estado aceptado; no había socket abierto para ' + `${producto}_${tipo}_${doc}`);
  else if (json?.errores?.[0]?.detalle?.includes('Failed to read HTTP message'))
    console.log('=> El ambiente no reconoce algún valor (estadoPaso, paso, tipoAfiliacion o tipo de documento): no está desplegado o no existe.');
  return estadoEnvio;
}

if (a['sin-socket']) {
  await enviar();
} else {
  const id = `${producto}_${tipo}_${doc}`;
  console.log(`Abriendo socket ${amb.socket} con id ${id}`);
  const ws = await abrirSocket(amb.socket, id);
  console.log('Socket abierto.\n');
  const estadoEnvio = await enviar();
  if (estadoEnvio === 'OK') {
    const msg = await ws.siguiente(espera);
    console.log('\nMensaje recibido por el socket:');
    console.log(msg ? JSON.stringify(JSON.parse(msg), null, 2) : `(nada en ${espera / 1000} s)`);
  }
  ws.cerrar();
}
