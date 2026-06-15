from jarvis.src.ai.llm import get_llm_response

print("="*50)
print("💻 Jarvis Terminal Local (Escribe 'salir' para terminar)")
print("="*50)

# Usamos un ID de usuario estático para simular que eres tú
USER_ID = "123456789" 

while True:
    mensaje = input("\nTú: ")
    if mensaje.lower() in ["salir", "exit", "quit"]:
        print("Cerrando terminal...")
        break
        
    if mensaje.strip():
        print("Jarvis está pensando...")
        respuesta = get_llm_response(USER_ID, mensaje)
        print(f"\n🤖 Jarvis: {respuesta}")