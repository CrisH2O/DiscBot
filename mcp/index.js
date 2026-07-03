import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { SSEServerTransport } from "@modelcontextprotocol/sdk/server/sse.js";
import { z } from "zod";
import axios from "axios";
import express from "express";
import cors from "cors";

// 1. Estado en memoria RAM (¡Adiós al archivo físico!)
let estadoActual = {
  gusto: 0, disgusto: 0, confianza: 0, curiosidad: 0, spice: 0, ansiedad: 0
};

// 2. Inicializamos el Servidor MCP
const server = new McpServer({ name: "Jarvis-Gateway", version: "1.0.0" });

// --- HERRAMIENTAS ---
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

// 3. Servidor de Red (SSE Transport)
const app = express();
app.use(cors());

let transport;

// Endpoint MCP (Para que Python envíe órdenes)
app.get("/sse", async (req, res) => {
  transport = new SSEServerTransport("/message", res);
  await server.connect(transport);
});

app.post("/message", async (req, res) => {
  if (transport) {
    await transport.handlePostMessage(req, res);
  }
});

// Endpoint UI (Para que el HTML pregunte cómo se siente Jarvis)
app.get("/api/estado", (req, res) => {
  res.json({ estado: estadoActual });
});

const PORT = 3001;
app.listen(PORT, () => {
  console.log(`✅ Servidor MCP iniciado.`);
  console.log(`📡 Escuchando por red (SSE) en http://localhost:${PORT}/sse`);
});