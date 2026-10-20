// Levanta en local el front de credito (clon de feat/consumer-loans) con
// `next dev`. Lo usa .claude/launch.json ("front-consumo-local").
//
//   node front_consumo_local.js [puerto]      (default 3005)
//
// La carpeta del clon sale de QA_FRONT_DIR; sin ella, ~/qa-front-consumo. Asi
// launch.json no lleva la ruta de nadie.
//
// Next corre dentro de este mismo proceso (require, no spawn): con un proceso
// hijo, al detener el preview se mataba este y Next seguia vivo con el puerto.
const fs = require("fs");
const os = require("os");
const path = require("path");

const dir = path.resolve(process.env.QA_FRONT_DIR
  || path.join(os.homedir(), "qa-front-consumo"));
const next = path.join(dir, "node_modules", "next", "dist", "bin", "next");
if (!fs.existsSync(next)) {
  console.error("No encuentro Next en " + next);
  console.error("Clona el front (rama feat/consumer-loans) y corre npm install;");
  console.error("si no quedo en ~/qa-front-consumo, define QA_FRONT_DIR con su carpeta:");
  console.error('  setx QA_FRONT_DIR "C:\\ruta\\al\\front"');
  process.exit(1);
}
const puerto = process.argv[2] || "3005";
console.log("Front local: " + dir + " en el puerto " + puerto);
// el CLI de Next lee sus argumentos de process.argv
process.argv = [process.argv[0], next, "dev", dir, "-p", puerto];
require(next);
