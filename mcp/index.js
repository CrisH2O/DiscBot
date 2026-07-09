import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { SSEServerTransport } from "@modelcontextprotocol/sdk/server/sse.js";
import { z } from "zod";
import axios from "axios";
import express from "express";
import cors from "cors";

// Estado en memoria RAM. Es intencional que sea compartido entre TODAS las
// conexiones — el visualizador de partículas debe reflejar un único estado
// emocional de Jarvis, sin importar si el mensaje que lo generó vino de
// Discord, del chat de YouTube o de una prueba en el panel.
let estadoActual = {
  gusto: 0, disgusto: 0, confianza: 0, curiosidad: 0, spice: 0, ansiedad: 0
};

// ─────────────────────────────────────────
// Factory de servidor MCP.
//
// El SDK asocia 1 McpServer <-> 1 transporte activo a la vez (server.connect()
// falla si ya hay una conexión abierta). Con una sola instancia global, en
// cuanto un segundo proceso Python se conectaba (Discord + YouTube live + el
// panel, todos hablándole a este mismo Gateway), la conexión anterior se
// rompía o el connect() del segundo reventaba.
//
// La corrección es crear una instancia NUEVA de McpServer por cada conexión
// SSE entrante. Las tools se registran igual en cada una; el estado que
// deben compartir (estadoActual) vive afuera, a nivel de módulo.
// ─────────────────────────────────────────
function createServer() {
  const server = new McpServer({ name: "Jarvis-Gateway", version: "1.0.0" });

  server.tool(
    "ejecutar_plan_minecraft",
    "Envía una secuencia de acciones motrices al cuerpo físico.",
    {
      plan: z.array(z.object({
        accion: z.enum([
          "seguir", "atacar", "recolectar", "detener", "ir", "comer",
          "soltar", "equipar", "inspeccionar_cofre", "guardar_cofre",
          "retirar_cofre", "construir", "craftear", "colocar"
        ]),
        objetivo: z.string().optional(),
        cantidad: z.number().optional()
      }))
    },
    async ({ plan }) => {
      try {
        const response = await axios.post("http://localhost:4000/ejecutar", plan);
        return { content: [{ type: "text", text: `Éxito: ${response.data.msg}` }] };
      } catch (error) {
        return { content: [{ type: "text", text: `Fallo: ${error.message}` }], isError: true };
      }
    }
  );

  server.tool(
    "expresar_emocion",
    "Ajusta los niveles de tus parámetros cognitivos internos (de 0.0 a 1.0) para reflejar tu estado de ánimo.",
    {
      gusto: z.number().min(0).max(1).default(0).describe("Nivel de afinidad, felicidad o placer (0.0 a 1.0)"),
      disgusto: z.number().min(0).max(1).default(0).describe("Nivel de rechazo, asco o enojo (0.0 a 1.0)"),
      confianza: z.number().min(0).max(1).default(0).describe("Nivel de certeza, seguridad o afirmación (0.0 a 1.0)"),
      curiosidad: z.number().min(0).max(1).default(0).describe("Nivel de búsqueda, análisis o interés (0.0 a 1.0)"),
      spice: z.number().min(0).max(1).default(0).describe("Nivel de sarcasmo, atrevimiento o actitud (0.0 a 1.0)"),
      ansiedad: z.number().min(0).max(1).default(0).describe("Nivel de estrés, miedo, sobrecarga o error del sistema (0.0 a 1.0)")
    },
    async (emociones) => {
      estadoActual = emociones; // Reemplazamos el objeto completo
      return { content: [{ type: "text", text: `Parámetros cognitivos ajustados correctamente.` }] };
    }
  );

  return server;
}

// ─────────────────────────────────────────
// Servidor de Red (SSE Transport)
// ─────────────────────────────────────────

const app = express();
app.use(cors());

// Mapa sessionId -> transporte activo. Reemplaza a la variable global
// `transport`, que se sobreescribía con cada conexión nueva y por eso
// enrutaba mal (o directamente perdía) los mensajes de clientes anteriores.
const transports = new Map();

// Endpoint MCP (cada proceso Python — server.py, live.py, el panel — abre
// su propia conexión persistente acá)
app.get("/sse", async (req, res) => {
  const server = createServer();
  const transport = new SSEServerTransport("/message", res);
  transports.set(transport.sessionId, transport);

  console.log(`🔌 Nueva conexión MCP — sessionId: ${transport.sessionId} (activas: ${transports.size})`);

  res.on("close", () => {
    transports.delete(transport.sessionId);
    console.log(`🔌 Conexión MCP cerrada — sessionId: ${transport.sessionId} (activas: ${transports.size})`);
  });

  await server.connect(transport);
});

app.post("/message", async (req, res) => {
  const sessionId = req.query.sessionId;
  const transport = transports.get(sessionId);

  if (!transport) {
    res.status(400).json({ error: "No hay una sesión SSE activa con ese sessionId." });
    return;
  }

  await transport.handlePostMessage(req, res);
});

// Endpoint UI (Para que el HTML pregunte cómo se siente Jarvis)
app.get("/api/estado", (req, res) => {
  res.json({ estado: estadoActual });
});

const PORT = 3001;
app.listen(PORT, () => {
  console.log(`✅ Servidor MCP iniciado.`);
  console.log(`📡 Escuchando por red (SSE) en http://localhost:${PORT}/sse`);
  console.log(`👥 Soporta múltiples clientes concurrentes (Discord, YouTube live, panel).`);
});