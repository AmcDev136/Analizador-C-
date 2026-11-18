"""
Puente entre el analizador léxico del equipo (analizador_lexico.py) y el resto
del compilador. analizador_lexico.py se usa tal cual, sin modificaciones.

Este módulo solo traduce el resultado al formato que esperan sintactico.py e
interfaz.py:

    analizar(codigo) -> (tokens: list[Token], errores: list[dict])

    * Los comentarios se descartan (no le sirven al sintáctico).
    * Se agrega la posición absoluta (inicio/fin) de cada token.
    * La lista termina con un token "EOF".
    * Cada error es un dict: fase, mensaje, linea, columna, sugerencia.
"""
import re
from dataclasses import dataclass

from analizador_lexico import AnalizadorLexicoCPP

PALABRAS_RESERVADAS = AnalizadorLexicoCPP.PALABRAS_RESERVADAS

TIPOS_PREDEFINIDOS = {"void", "bool", "char", "wchar_t", "char8_t", "char16_t", "char32_t",
                      "short", "int", "long", "float", "double", "signed", "unsigned", "auto"}

# Categoría del léxico del equipo → tipo que usa el sintáctico
MAPA_TIPOS = {
    "Palabra reservada": "RESERVADA",
    "Literal booleano/nulo": "RESERVADA",
    "Identificador": "IDENTIFICADOR",
    "Entero": "ENTERO",
    "Flotante": "REAL",
    "Cadena": "CADENA",
    "Carácter": "CARACTER",
    "Operador": "OPERADOR",
    "Delimitador": "DELIMITADOR",
    "Directiva": "DIRECTIVA",
    "Cabecera": "CABECERA",
}

SUGERENCIAS = [
    ("numérico", "Un identificador no puede empezar con un dígito; revisa también los sufijos (u, l, f)."),
    ("cadena raw", 'Revisa el formato R"delim( ... )delim".'),
    ("cadena", 'Agrega la comilla de cierre (") en la misma línea.'),
    ("carácter sin cerrar", "Cierra el literal con comilla simple: 'a'."),
    ("vacío", "Un char lleva exactamente un carácter: 'a'."),
    ("comentario", "Cierra el comentario con */."),
    ("cabecera", "Cierra la cabecera con '>': #include <iostream>."),
    ("no reconocido", "Elimina el carácter; no forma parte de ningún token de C++."),
]


@dataclass
class Token:
    tipo: str            # RESERVADA, IDENTIFICADOR, ENTERO, REAL, CADENA, ...
    lexema: str
    linea: int
    columna: int
    inicio: int = 0      # índice absoluto en el código
    fin: int = 0
    categoria: str = ""  # nombre original del léxico del equipo

    def __repr__(self):
        return f"<{self.tipo} '{self.lexema}' {self.linea}:{self.columna}>"


def _sugerencia(mensaje):
    m = mensaje.lower()
    return next((s for clave, s in SUGERENCIAS if clave in m), "")


def analizar(codigo: str):
    res = AnalizadorLexicoCPP(codigo).analizar()
    inicios = [0] + [m.end() for m in re.finditer("\n", codigo)]

    tokens = []
    for t in res.tokens:
        if t.tipo == "Comentario":
            continue
        ini = inicios[t.linea - 1] + t.columna - 1
        tokens.append(Token(MAPA_TIPOS.get(t.tipo, "OPERADOR"), t.lexema, t.linea, t.columna,
                            ini, ini + len(t.lexema), t.tipo))
    tokens.append(Token("EOF", "fin de archivo", len(inicios), len(codigo) - inicios[-1] + 1,
                        len(codigo), len(codigo), "Fin"))

    errores = [{"fase": "Léxico", "mensaje": e.mensaje.rstrip("."), "linea": e.linea,
                "columna": e.columna, "lexema": e.lexema, "sugerencia": _sugerencia(e.mensaje),
                "esperado": "token válido", "encontrado": repr(e.lexema[:20])}
               for e in res.errores]
    return tokens, errores
