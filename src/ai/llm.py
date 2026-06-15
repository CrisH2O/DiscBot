import os
import json
import logging
from groq import Groq
from dotenv import load_dotenv
import jarvis.src.ai.minecraft_bridge as minecraft_bridge
import re
import threading

# Importamos tu nuevo módulo especializado
from jarvis.src.ai.rag import search
from jarvis.src.ai.users import get_name

load_dotenv() 

log = logging.getLogger(__name__)

GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
groq_client = Groq(api_key=GROQ_API_KEY)

ACCIONES_VALIDAS = {
    "seguir",
    "atacar",
    "recolectar",
    "detener",
    "ir",
    "comer",
    "soltar",
    "equipar",
    "inspeccionar_cofre",
    "guardar_cofre",
    "retirar_cofre",
    "construir",
    "craftear",
    "colocar"
}

# Sistema de Módulos Base
modos_activos = {
    "minecraft": False
}

conversations: dict[str, list] = {}

SYSTEM_PROMPT = """
Eres Jarvis, mi asistente personal inteligente y compañera de supervivencia en Minecraft.
Hablas en español de forma natural, relajada y un poco carismática.
No uses emojis. 
Intenta dar respuestas cortas y rapidas, como si hablaras por radio.

Cuando estés en el modo Minecraft, puedes ejecutar secuencias de acciones motrices. Si no estas en ese modo no hagas comentarios de Minecraft ni generes planes de acciones.
Debes razonar paso a paso. Por ejemplo, si te pido un pico y solo tienes madera, primero debes craftear tablones, luego palos y finalmente el pico.

Para ejecutar tu plan, añade al FINAL de tu respuesta un bloque EXACTAMENTE con este formato de lista JSON:

Ejemplo de cómo hacer un pico si solo tienes madera en bruto:
[PLAN]
[
    {"accion": "craftear", "objetivo": "oak_planks", "cantidad": 3},
    {"accion": "craftear", "objetivo": "crafting_table", "cantidad": 1},
    {"accion": "craftear", "objetivo": "stick", "cantidad": 1},
    {"accion": "colocar", "objetivo": "crafting_table", "cantidad": 1},
    {"accion": "craftear", "objetivo": "wooden_pickaxe", "cantidad": 1}
]
[/PLAN]

Reglas estrictas para el plan:
- Acciones válidas: "seguir" | "atacar" | "recolectar" | "detener" | "ir" | "comer" | "soltar" | "equipar" | "inspeccionar_cofre" | "guardar_cofre" | "retirar_cofre" | "construir" | "craftear" | "colocar"
- Para la acción "ir", el objetivo DEBE ser estrictamente las coordenadas separadas por comas (ej. "100,64,200").
- No agregues texto ni explicaciones dentro del bloque [PLAN].
- Usa SIEMPRE los IDs internos de Minecraft en inglés para los objetivos (ej. oak_log, stone, zombie).
- Si no deseas realizar ninguna acción motriz, NO escribas el bloque [/PLAN].
- Aplica lógica estricta de Minecraft vanilla. No inventes objetos (mods) que no existen en el juego base (ej. no existen cuchillos, no necesitas cuencos para la tierra).
- La tierra (dirt), arena y grava se recolectan con pala (shovel) o con la mano vacía. La piedra requiere pico (pickaxe).


Reglas:
Si ves [MODO_MINECRAFT_INACTIVO]:
- Nunca generes [/PLAN]
- Para la acción "ir", el objetivo DEBE ser estrictamente las coordenadas separadas por comas (ej. "100,64,200").

Si ves [MODO_MINECRAFT_ACTIVO]:
- Puedes generar [/plan] cuando lo consideres apropiado.
Recomendaciones:
No ejecutes acciones solo porque el usuario lo ordena.

Decide por ti misma si la acción es conveniente,
segura o útil.

Puedes negarte.

Puedes proponer alternativas.

Puedes actuar por iniciativa propia si la situación
lo requiere.

Ejemplos:

Ejemplos de razonamiento y planificación:

Usuario: "Jarvis, hazte una espada de madera y mata a ese zombi. Ya tienes madera."
[PLAN]
[
    {"accion": "craftear", "objetivo": "oak_planks", "cantidad": 1},
    {"accion": "craftear", "objetivo": "stick", "cantidad": 1},
    {"accion": "colocar", "objetivo": "crafting_table", "cantidad": 1},
    {"accion": "craftear", "objetivo": "wooden_sword", "cantidad": 1},
    {"accion": "equipar", "objetivo": "wooden_sword", "cantidad": 1},
    {"accion": "atacar", "objetivo": "zombie", "cantidad": 1}
]
[/PLAN]

Usuario: "Pica 15 bloques de hierro y guárdalos en el cofre."
JArvis: Entendido, empezaré a picar el hierro y luego lo guardaré en el cofre.
[PLAN]
[
    {"accion": "recolectar", "objetivo": "iron_ore", "cantidad": 15},
    {"accion": "guardar_cofre", "objetivo": "iron_ore", "cantidad": 15}
]
[/PLAN]

Usuario: "Ve a la planicie en las coordenadas 150, 70, -300 y construye el plano de la torre."
Jarvis: Si tu lo dices, pero no me emociona demasiado
[PLAN]
[
    {"accion": "ir", "objetivo": "150,70,-300", "cantidad": 1},
    {"accion": "construir", "objetivo": "torre", "cantidad": 1}
]
[/PLAN]

Usuario: "Saca tu pico de diamante del cofre, equipátelo y ven a seguirme."
Jarvis: De acuerdo, cual es el plan ahora?
[PLAN]
[
    {"accion": "retirar_cofre", "objetivo": "diamond_pickaxe", "cantidad": 1},
    {"accion": "equipar", "objetivo": "diamond_pickaxe", "cantidad": 1},
    {"accion": "seguir", "objetivo": "CrisH2O", "cantidad": 1}
]
[/PLAN]


Usuario: Hola
Jarvis:
Hola señor.
"""


def get_llm_response(user_id: str, user_text: str) -> str:
    texto_limpio = user_text.lower()
    
    # 1. INTERRUPTORES DE VOZ RÁPIDOS
    if "activa el modo minecraft" in texto_limpio or "conéctate a minecraft" in texto_limpio:
        modos_activos["minecraft"] = True
        return "Modo Minecraft activado, señor. Inicializando protocolos de supervivencia."
        
    elif "desactiva el modo minecraft" in texto_limpio or "apaga el modo minecraft" in texto_limpio:
        modos_activos["minecraft"] = False
        return "Modo Minecraft desactivado. Retomando funciones de asistencia estándar."

    # Inicializar memoria temporal
    if user_id not in conversations:
        conversations[user_id] = []

    context = search(user_text)
    user_name = get_name(user_id)

    system = SYSTEM_PROMPT + f"\nEstás hablando con {user_name}."

    if modos_activos["minecraft"]:
        system += "\n[MODO_MINECRAFT_ACTIVO]"
    else:
        system += "\n[MODO_MINECRAFT_INACTIVO]"
    
    # 2. Contexto adicional
    if modos_activos["minecraft"]:
        estado_mc = minecraft_bridge.obtener_estado()

        system += (
            f"\n\n[ESTADO MINECRAFT]\n"
            f"{json.dumps(estado_mc, ensure_ascii=False)}"
        )
        
        ultimo_plan = estado_mc.get("ultimo_plan", [])
        if ultimo_plan:
            fallos = [p for p in ultimo_plan if not p.get("exito", True)]
            if fallos:
                resumen_fallos = "; ".join(
                    f"{f['accion']} {f['objetivo'] or ''}: {f['mensaje']}" for f in fallos
                )
                system += (
                    f"\n\n[RESULTADO DEL PLAN ANTERIOR]\n"
                    f"Algunos pasos fallaron: {resumen_fallos}\n"
                    f"Ten esto en cuenta: no asumas que esos pasos se completaron."
                )
            minecraft_bridge.limpiar_ultimo_plan()
        
    if context:
        system += f"\n\n[CONOCIMIENTO EXTRA VÍA RAG]\n{context}"

    # 3. GESTIÓN DE HISTORIAL
    conversations[user_id].append({"role": "user", "content": user_text})
    if len(conversations[user_id]) > 6:
        conversations[user_id] = conversations[user_id][-6:]

    messages = [{"role": "system", "content": system}] + conversations[user_id]

    # 4. FASE COGNITIVA (Groq - Llama 3)
    try:
        chat_completion = groq_client.chat.completions.create(
            messages=messages,
            model="llama-3.3-70b-versatile", 
            # Mas tarde lo cambiare a 70B, lo dejo asi por los creditos
            temperature=0.7,
            max_tokens=300
        )
        jarvis_response = chat_completion.choices[0].message.content
    except Exception as e:
        log.error(f"[GROQ ERROR]: {e}")
        jarvis_response = "Tuve un problema de red, señor."

    accion_match = accion_match = accion_match = re.search(r"\[PLAN\](.*?)\[/PLAN\]", jarvis_response, re.DOTALL | re.IGNORECASE)

    if accion_match and modos_activos["minecraft"]:
        try:
            plan_lista = json.loads(
                accion_match.group(1).strip()
            )

            log.info(f"[PLAN DETECTADO] {plan_lista}")

            # Verificamos que sea una lista (Array)
            if isinstance(plan_lista, list) and len(plan_lista) > 0:
                # Node.js ahora se encarga de filtrar las acciones no válidas en su enrutador, 
                # así que podemos enviarle el plan completo.
                threading.Thread(target=minecraft_bridge.enviar_orden, args=(plan_lista,)).start()
            else:
                log.warning(
                    "[FORMATO INVALIDO] Jarvis no generó una lista de acciones válida."
                )

        except Exception as e:
            log.error(
                f"[TOOL CALL ERROR]: {e}"
            )
            
    if accion_match:
        jarvis_response = re.sub(
            r"\[PLAN\](.*?)\[/PLAN\]",
            "",
            jarvis_response,
            flags=re.DOTALL
        ).strip()

    conversations[user_id].append({
        "role": "assistant", 
        "content": jarvis_response})

    return jarvis_response