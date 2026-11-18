"""
Analizador SINTÁCTICO de C++ (descenso recursivo, subconjunto del lenguaje).

Contrato para unir con las otras fases:

    analizar(tokens) -> ResultadoSintactico
        .arbol    Nodo raíz ("Programa")
        .errores  list[dict]  (fase, mensaje, linea, columna, sugerencia)
        .pasos    list[dict]  traza paso a paso para la interfaz
        .nodos    list[Nodo]  todos los nodos en preorden

El semántico recibe .arbol (Nodo con tipo, valor, hijos, linea, columna).

Gramática (EBNF simplificada)
-----------------------------
programa     → { directiva | using | namespace | clase | enum | typedef
                 | template | declaración_externa }
directiva    → '#' IDENT ( CABECERA | CADENA | resto de la línea )
using        → 'using' 'namespace' nombre ';' | 'using' nombre ';'
clase        → ('class'|'struct') IDENT [':' base {',' base}]
               '{' { especificador_acceso ':' | miembro } '}' ';'
decl_externa → { especificador } tipo { '*' | '&' } nombre
               ( '(' parámetros ')' [ 'const' ] ( bloque | ';' )
               | declarador { ',' declarador } ';' )
declarador   → { '*' | '&' } IDENT { '[' [expr] ']' }
               [ '=' (expr | '{' lista '}') | '(' args ')' | '{' lista '}' ]
sentencia    → bloque | declaración ';' | if | while | do | for | switch
               | return | break | continue | try | throw | expresión ';' | ';'
expresión    → asignación → ternario → || → && → | → ^ → & → == != →
               < > <= >= → << >> → + - → * / % → unaria → postfija → primaria
"""
from dataclasses import dataclass, field
from itertools import count
from lexico import Token, TIPOS_PREDEFINIDOS

ESPECIFICADORES = {"static", "const", "constexpr", "inline", "virtual", "extern", "explicit",
                   "friend", "mutable", "volatile", "register", "thread_local", "consteval"}
ACCESO = {"public", "private", "protected"}
OPS_ASIGNACION = {"=", "+=", "-=", "*=", "/=", "%=", "&=", "|=", "^=", "<<=", ">>="}
CASTS = {"static_cast", "dynamic_cast", "const_cast", "reinterpret_cast"}

NOMBRES_REGLA = {
    "programa": "Programa", "directiva": "Directiva del preprocesador",
    "using": "Directiva using", "namespace": "Espacio de nombres",
    "clase": "Declaración de clase", "enum": "Enumeración", "typedef": "Typedef",
    "template": "Plantilla", "decl_externa": "Declaración",
    "miembro": "Miembro de clase", "funcion": "Definición de función",
    "constructor": "Constructor", "destructor": "Destructor",
    "parametros": "Lista de parámetros", "tipo": "Tipo", "bloque": "Bloque",
    "decl_local": "Declaración de variable", "declarador": "Declarador",
    "if": "Sentencia if", "while": "Ciclo while", "do": "Ciclo do-while",
    "for": "Ciclo for", "switch": "Sentencia switch", "return": "Sentencia return",
    "salto": "Sentencia de salto", "try": "Bloque try-catch", "throw": "Sentencia throw",
    "expr_sent": "Sentencia de expresión", "asignacion": "Asignación",
    "condicional": "Expresión condicional", "binaria": "Expresión binaria",
    "unaria": "Expresión unaria", "postfija": "Acceso a miembro",
    "llamada": "Llamada a función", "argumentos": "Lista de argumentos",
    "primaria": "Expresión primaria", "new": "Expresión new", "lista": "Lista de inicialización",
}

SUGERENCIAS = {
    ";": "Agrega ';' al final de la instrucción (también después de la '}' de una clase o struct).",
    ")": "Revisa que cada '(' tenga su ')' correspondiente.",
    "]": "Revisa que cada '[' tenga su ']' correspondiente.",
    "}": "Revisa que cada '{' tenga su '}' correspondiente.",
    "{": "Los cuerpos de funciones, clases y bloques empiezan con '{'.",
    "(": "Después de if, while, for, switch o del nombre de una función va '('.",
    ">": "Cierra la lista de la plantilla con '>': vector<int>.",
    ":": "Después de public, private, protected, case o default va ':'.",
    "IDENTIFICADOR": "Escribe un nombre válido (letra o _ seguido de letras, dígitos o _).",
    "expresión": "Escribe un valor, variable, llamada u operación antes de este punto.",
    "tipo": "Indica un tipo válido: int, double, char, bool, std::string o el nombre de una clase.",
    "cabecera": "Escribe la cabecera entre <> o comillas: #include <iostream>.",
}

_ids = count(1)


@dataclass
class Nodo:
    tipo: str
    valor: str = ""
    linea: int = 0
    columna: int = 0
    hijos: list = field(default_factory=list)
    tok_ini: int = 0
    id: int = field(default_factory=lambda: next(_ids))

    def agregar(self, *hijos):
        for h in hijos:
            if h is not None:
                self.hijos.append(h)
        return self

    def etiqueta(self):
        return f"{self.tipo}: {self.valor}" if self.valor else self.tipo

    def preorden(self):
        yield self
        for h in self.hijos:
            yield from h.preorden()

    def como_texto(self, nivel=0):
        s = "  " * nivel + self.etiqueta() + (f"  [{self.linea}:{self.columna}]" if self.linea else "") + "\n"
        return s + "".join(h.como_texto(nivel + 1) for h in self.hijos)


@dataclass
class ResultadoSintactico:
    arbol: Nodo
    errores: list
    pasos: list
    nodos: list


class ErrorSintactico(Exception):
    pass


class Parser:
    MAX_ERRORES = 25

    def __init__(self, tokens):
        self.t = list(tokens)
        self.p = 0
        self.pila, self.pasos, self.errores = [], [], []
        self.clases = set()          # nombres de clases/structs declarados

    # ───────────────────────── utilidades ─────────────────────────
    @property
    def actual(self) -> Token:
        return self.t[self.p]

    def ver(self, k=0) -> Token:
        return self.t[min(self.p + k, len(self.t) - 1)]

    def es(self, *lexemas, k=0):
        t = self.ver(k)
        return t.lexema in lexemas and t.tipo not in ("CADENA", "CARACTER", "EOF")

    def es_tipo(self, tipo, k=0):
        return self.ver(k).tipo == tipo

    def es_reservada(self, conjunto, k=0):
        t = self.ver(k)
        return t.tipo == "RESERVADA" and t.lexema in conjunto

    def nodo(self, tipo, valor="", tok=None):
        tok = tok or self.actual
        return Nodo(tipo, valor, tok.linea, tok.columna, tok_ini=min(self.p, len(self.t) - 1))

    def entrar(self, regla):
        self.pila.append(NOMBRES_REGLA.get(regla, regla))

    def salir(self):
        self.pila.pop()

    def _paso(self, tipo, tok, esperado, mensaje="", sugerencia=""):
        self.pasos.append({
            "tipo": tipo, "regla": self.pila[-1] if self.pila else "",
            "pila": list(self.pila), "token": tok, "indice": self.p,
            "esperado": esperado,
            "encontrado": tok.lexema if tok.tipo != "EOF" else "fin de archivo",
            "mensaje": mensaje, "sugerencia": sugerencia,
        })

    def consumir(self, esperado_desc=None):
        tok = self.actual
        self._paso("match", tok, esperado_desc or f"'{tok.lexema}'",
                   f"Se reconoce {tok.tipo.lower()} '{tok.lexema}'")
        if tok.tipo != "EOF":
            self.p += 1
        return tok

    def esperar(self, lexema):
        if self.es(lexema):
            return self.consumir(f"'{lexema}'")
        self.error(f"'{lexema}'", SUGERENCIAS.get(lexema, ""))

    def esperar_ident(self):
        if self.es_tipo("IDENTIFICADOR"):
            return self.consumir("IDENTIFICADOR")
        self.error("un identificador", SUGERENCIAS["IDENTIFICADOR"])

    def error(self, esperado, sugerencia="", lanzar=True):
        tok = self.actual
        encontrado = "fin de archivo" if tok.tipo == "EOF" else f"'{tok.lexema}'"
        linea, col = tok.linea, tok.columna
        # Si falta un cierre, se reporta al final del token anterior
        if esperado in ("';'", "')'", "']'") and self.p > 0:
            ant = self.t[self.p - 1]
            if ant.linea != tok.linea:
                linea, col = ant.linea, ant.columna + len(ant.lexema)
        msg = f"Se esperaba {esperado} y se encontró {encontrado}"
        err = {"fase": "Sintáctico", "mensaje": msg, "linea": linea, "columna": col,
               "sugerencia": sugerencia, "esperado": esperado, "encontrado": encontrado,
               "regla": self.pila[-1] if self.pila else ""}
        if not any(e["linea"] == linea and e["columna"] == col for e in self.errores):
            self.errores.append(err)
            self._paso("error", tok, esperado, msg, sugerencia)
        if len(self.errores) >= self.MAX_ERRORES:
            raise OverflowError
        if lanzar:
            raise ErrorSintactico(msg)

    def sincronizar(self, hasta=(";", "}")):
        """Modo pánico: descarta tokens hasta un punto seguro."""
        inicio = self.p
        inicios = {"if", "while", "for", "do", "return", "switch", "break", "continue", "try"}
        while self.actual.tipo != "EOF":
            if self.es(";") and ";" in hasta:
                self.p += 1
                return
            if self.es("}", "{") and "}" in hasta:
                return
            if self.p > inicio and self.actual.lexema in inicios and self.actual.tipo == "RESERVADA":
                return
            if self.p > inicio and self.actual.tipo == "DIRECTIVA":
                return
            if (self.p > inicio and self.actual.linea > self.t[self.p - 1].linea
                    and (self.es_declaracion() or self.es_tipo("IDENTIFICADOR"))):
                return
            self.p += 1

    def saltar_balanceado(self):
        prof = 0
        while self.actual.tipo != "EOF":
            if self.es("{"):
                prof += 1
            elif self.es("}"):
                prof -= 1
                if prof == 0:
                    self.p += 1
                    if self.es(";"):
                        self.p += 1
                    return
            self.p += 1

    def proteger(self, fn, sinc=(";", "}")):
        """Ejecuta una regla; si falla, sincroniza y continúa."""
        nivel = len(self.pila)
        try:
            return fn()
        except ErrorSintactico:
            del self.pila[nivel:]
            self.sincronizar(sinc)
            if self.es("{"):                    # descartar el cuerpo completo
                self.saltar_balanceado()
            return None

    def partir_mayor(self):
        """El léxico entrega '>>' como un token; al cerrar plantillas son dos '>'."""
        t = self.actual
        a = Token("OPERADOR", ">", t.linea, t.columna, t.inicio, t.inicio + 1, "Operador")
        b = Token("OPERADOR", ">", t.linea, t.columna + 1, t.inicio + 1, t.fin, "Operador")
        self.t[self.p:self.p + 1] = [a, b]

    # ───────────────────────── nivel superior ─────────────────────────
    def programa(self):
        self.entrar("programa")
        raiz = self.nodo("Programa", tok=self.t[0])
        while self.actual.tipo != "EOF":
            antes = self.p
            raiz.agregar(self.proteger(self.declaracion_superior))
            if self.p == antes:
                self.p += 1
        self.salir()
        return raiz

    def declaracion_superior(self):
        if self.es_tipo("DIRECTIVA") or self.es("#"):
            return self.directiva()
        if self.es("using"):
            return self.s_using()
        if self.es("namespace"):
            return self.namespace()
        if self.es("template"):
            return self.template()
        if self.es("typedef"):
            return self.typedef()
        if self.es("enum"):
            return self.enum()
        if self.es("class", "struct", "union") and self.es_tipo("IDENTIFICADOR", k=1) \
                and self.es("{", ":", ";", k=2):
            return self.clase()
        if self.es(";"):
            n = self.nodo("DeclaraciónVacía")
            self.consumir("';'")
            return n
        return self.decl_externa()

    def directiva(self):
        self.entrar("directiva")
        n = self.nodo("Directiva")
        gato = self.consumir("'#'")
        nombre = self.esperar_ident() if not self.es_reservada({"if", "else", "define"}) \
            else self.consumir("directiva")
        n.valor = nombre.lexema
        if nombre.lexema == "include":
            if self.es_tipo("CABECERA") or self.es_tipo("CADENA"):
                n.valor += " " + self.consumir("cabecera").lexema
            else:
                self.error("una cabecera <...> o \"...\"", SUGERENCIAS["cabecera"])
        else:                                   # resto de la línea: #define X 10
            partes = []
            while self.actual.tipo != "EOF" and self.actual.linea == gato.linea:
                partes.append(self.consumir("contenido de la directiva").lexema)
            if partes:
                n.valor += " " + " ".join(partes)
        self.salir()
        return n

    def nombre_calificado(self, permitir_destructor=False):
        """IDENT { '::' IDENT }  (con '::' inicial opcional)."""
        primero = self.actual
        partes = []
        if self.es("::"):
            self.consumir("'::'")
            partes.append("")
        while True:
            if permitir_destructor and self.es("~") and partes:
                self.consumir("'~'")
                partes.append("~" + self.esperar_ident().lexema)
            else:
                partes.append(self.esperar_ident().lexema)
            if self.es("::") and (self.es_tipo("IDENTIFICADOR", k=1) or self.es("~", k=1)):
                self.consumir("'::'")
                continue
            break
        return "::".join(partes), primero

    def s_using(self):
        self.entrar("using")
        n = self.nodo("DirectivaUsing")
        self.consumir("'using'")
        if self.es("namespace"):
            self.consumir("'namespace'")
            n.tipo = "UsingNamespace"
        n.valor, _ = self.nombre_calificado()
        if self.es("="):                        # using Alias = tipo;
            self.consumir("'='")
            n.agregar(self.tipo())
        self.esperar(";")
        self.salir()
        return n

    def namespace(self):
        self.entrar("namespace")
        n = self.nodo("EspacioNombres")
        self.consumir("'namespace'")
        if self.es_tipo("IDENTIFICADOR"):
            n.valor, _ = self.nombre_calificado()
        self.esperar("{")
        while not self.es("}") and self.actual.tipo != "EOF":
            antes = self.p
            n.agregar(self.proteger(self.declaracion_superior))
            if self.p == antes:
                self.p += 1
        self.esperar("}")
        self.salir()
        return n

    def template(self):
        self.entrar("template")
        n = self.nodo("Plantilla")
        self.consumir("'template'")
        self.esperar("<")
        params = []
        while not self.es(">") and self.actual.tipo != "EOF":
            if self.es("typename", "class"):
                self.consumir("'typename' o 'class'")
                params.append(self.esperar_ident().lexema)
            else:
                t = self.tipo()
                params.append(f"{t.valor} {self.esperar_ident().lexema}")
            if not self.es(","):
                break
            self.consumir("','")
        if self.es(">>"):
            self.partir_mayor()
        self.esperar(">")
        n.valor = ", ".join(params)
        self.salir()
        if self.es("class", "struct"):
            n.agregar(self.clase())
        else:
            n.agregar(self.decl_externa())
        return n

    def typedef(self):
        self.entrar("typedef")
        n = self.nodo("Typedef")
        self.consumir("'typedef'")
        t = self.tipo()
        t.valor += self.punteros()
        n.agregar(t)
        n.valor = self.esperar_ident().lexema
        self.esperar(";")
        self.salir()
        return n

    def enum(self):
        self.entrar("enum")
        n = self.nodo("Enumeración")
        self.consumir("'enum'")
        if self.es("class", "struct"):
            self.consumir("'class'")
        n.valor = self.esperar_ident().lexema
        if self.es(":"):
            self.consumir("':'")
            n.agregar(self.tipo())
        if self.es("{"):
            self.consumir("'{'")
            while self.es_tipo("IDENTIFICADOR"):
                v = self.nodo("Enumerador", self.consumir("IDENTIFICADOR").lexema)
                if self.es("="):
                    self.consumir("'='")
                    v.agregar(self.expresion())
                n.agregar(v)
                if not self.es(","):
                    break
                self.consumir("','")
            self.esperar("}")
        self.esperar(";")
        self.salir()
        return n

    # ───────────────────────── clases ─────────────────────────
    def clase(self):
        self.entrar("clase")
        n = self.nodo("Clase")
        palabra = self.consumir("'class' o 'struct'").lexema
        if palabra != "class":
            n.tipo = "Estructura" if palabra == "struct" else "Unión"
        nombre = self.esperar_ident()
        n.valor = nombre.lexema
        self.clases.add(nombre.lexema)
        if self.es(";"):                        # declaración adelantada
            self.consumir("';'")
            self.salir()
            return n
        if self.es(":"):
            self.consumir("':'")
            herencia = self.nodo("Hereda")
            while True:
                acc = ""
                while self.es("public", "private", "protected", "virtual"):
                    acc += self.consumir("especificador de acceso").lexema + " "
                b = self.tipo()
                b.valor = acc + b.valor
                herencia.agregar(b)
                if not self.es(","):
                    break
                self.consumir("','")
            n.agregar(herencia)
        self.esperar("{")
        while not self.es("}") and self.actual.tipo != "EOF":
            antes = self.p
            if self.es_reservada(ACCESO) and self.es(":", k=1):
                acc = self.nodo("Acceso", self.consumir("especificador de acceso").lexema)
                self.consumir("':'")
                n.agregar(acc)
                continue
            n.agregar(self.proteger(lambda: self.miembro(nombre.lexema)))
            if self.p == antes:
                self.p += 1
        self.esperar("}")
        if self.es_tipo("IDENTIFICADOR"):       # struct P { ... } p1, p2;
            while True:
                n.agregar(self.nodo("Variable", self.consumir("IDENTIFICADOR").lexema))
                if not self.es(","):
                    break
                self.consumir("','")
        if self.es(";"):
            self.consumir("';'")
        else:                       # error frecuente: olvidar '};' — se reporta y se sigue
            self.error("';'", SUGERENCIAS[";"], lanzar=False)
        self.salir()
        return n

    def miembro(self, nombre_clase):
        if self.es("class", "struct", "union") and self.es_tipo("IDENTIFICADOR", k=1):
            return self.clase()
        if self.es("enum"):
            return self.enum()
        if self.es("using"):
            return self.s_using()
        if self.es("template"):
            return self.template()
        self.entrar("miembro")
        ini, tok0 = self.p, self.actual
        mods = self.especificadores()
        # constructor:  Nombre(...)
        if self.actual.lexema == nombre_clase and self.es("(", k=1):
            self.salir()
            n = self.constructor(ini, tok0, mods)
            return n
        # destructor:  ~Nombre()
        if self.es("~") and self.ver(1).lexema == nombre_clase:
            self.salir()
            self.entrar("destructor")
            self.consumir("'~'")
            n = Nodo("Destructor", "~" + self.consumir("IDENTIFICADOR").lexema,
                     tok0.linea, tok0.columna, tok_ini=ini)
            self._mods(n, mods)
            n.agregar(self.parametros())
            self.cola_funcion(n)
            self.salir()
            return n
        self.salir()
        return self.resto_declaracion(ini, tok0, mods, miembro=True)

    def constructor(self, ini, tok0, mods):
        self.entrar("constructor")
        n = Nodo("Constructor", self.consumir("IDENTIFICADOR").lexema, tok0.linea, tok0.columna, tok_ini=ini)
        self._mods(n, mods)
        n.agregar(self.parametros())
        if self.es(":"):                        # lista de inicialización
            self.consumir("':'")
            lista = self.nodo("ListaInicialización")
            while True:
                campo = self.nodo("Inicializa", self.esperar_ident().lexema)
                if self.es("{"):
                    campo.agregar(self.lista_init())
                else:
                    campo.agregar(self.argumentos())
                lista.agregar(campo)
                if not self.es(","):
                    break
                self.consumir("','")
            n.agregar(lista)
        self.cola_funcion(n)
        self.salir()
        return n

    def _mods(self, n, mods):
        if mods:
            n.agregar(Nodo("Especificadores", " ".join(mods), n.linea, n.columna, tok_ini=n.tok_ini))

    def especificadores(self):
        mods = []
        while self.es_reservada(ESPECIFICADORES - {"const", "volatile"}):
            mods.append(self.consumir("especificador").lexema)
        return mods

    # ───────────────────────── declaraciones ─────────────────────────
    def decl_externa(self):
        ini, tok0 = self.p, self.actual
        mods = self.especificadores()
        # constructor/destructor definido fuera de la clase:  Clase::Clase(...)
        if self.es_tipo("IDENTIFICADOR") and self.es("::", k=1) \
                and (self.ver(2).lexema == self.actual.lexema or self.es("~", k=2)):
            return self.funcion_fuera(ini, tok0, mods)
        return self.resto_declaracion(ini, tok0, mods)

    def funcion_fuera(self, ini, tok0, mods):
        self.entrar("constructor")
        nombre, _ = self.nombre_calificado(permitir_destructor=True)
        es_destructor = "~" in nombre
        n = Nodo("Destructor" if es_destructor else "Constructor", nombre,
                 tok0.linea, tok0.columna, tok_ini=ini)
        self._mods(n, mods)
        n.agregar(self.parametros())
        if self.es(":") and not es_destructor:
            self.consumir("':'")
            lista = self.nodo("ListaInicialización")
            while True:
                campo = self.nodo("Inicializa", self.esperar_ident().lexema)
                campo.agregar(self.lista_init() if self.es("{") else self.argumentos())
                lista.agregar(campo)
                if not self.es(","):
                    break
                self.consumir("','")
            n.agregar(lista)
        self.cola_funcion(n)
        self.salir()
        return n

    def resto_declaracion(self, ini, tok0, mods, miembro=False):
        """tipo {*|&} nombre ( función | variables )"""
        self.entrar("decl_externa")
        if not self.es_inicio_tipo():
            self.error("un tipo", SUGERENCIAS["tipo"])
        tipo = self.tipo()
        ptr = self.punteros()
        if self.es("operator"):                 # sobrecarga de operadores
            self.consumir("'operator'")
            op = self.consumir("operador").lexema
            if op in ("(", "["):
                op += self.consumir("cierre").lexema
            nombre, ntok = "operator" + op, tok0
        else:
            nombre, ntok = self.nombre_calificado()
        if self.es("("):
            self.salir()
            self.entrar("funcion")
            n = Nodo("Función" if not miembro else "Método", nombre, tok0.linea, tok0.columna, tok_ini=ini)
            self._mods(n, mods)
            tipo.valor += ptr
            n.agregar(tipo, self.parametros())
            self.cola_funcion(n)
            self.salir()
            return n
        # variables (globales o campos)
        n = Nodo("Campo" if miembro else "DeclaraciónGlobal", "", tok0.linea, tok0.columna, tok_ini=ini)
        self._mods(n, mods)
        n.agregar(tipo)
        n.agregar(self.declarador(ptr, ntok, nombre))
        while self.es(","):
            self.consumir("','")
            n.agregar(self.declarador())
        self.esperar(";")
        self.salir()
        return n

    def cola_funcion(self, n):
        """Lo que sigue a ')' en una función: calificadores y cuerpo o ';'."""
        while self.es("const", "override", "final", "noexcept"):
            n.agregar(self.nodo("Calificador", self.consumir("calificador").lexema))
        if self.es("="):                        # = 0;  = default;  = delete;
            self.consumir("'='")
            n.agregar(self.nodo("Igual", self.consumir("0, default o delete").lexema))
            self.esperar(";")
        elif self.es("{"):
            n.agregar(self.bloque())
        else:
            self.esperar(";")                   # prototipo
            n.tipo = "Prototipo"

    def punteros(self):
        s = ""
        while self.es("*", "&", "&&") or (s and self.es("const")):
            s += self.consumir("'*' o '&'").lexema
        return s

    def declarador(self, ptr=None, nombre_tok=None, nombre=None):
        self.entrar("declarador")
        if ptr is None:
            ptr = self.punteros()
            nombre_tok = self.esperar_ident()
            nombre = nombre_tok.lexema
        d = Nodo("Variable", ptr + nombre, nombre_tok.linea, nombre_tok.columna,
                 tok_ini=self.t.index(nombre_tok) if nombre_tok in self.t else self.p)
        while self.es("["):
            self.consumir("'['")
            dim = self.nodo("Dimensión")
            if not self.es("]"):
                dim.agregar(self.expresion())
            self.esperar("]")
            d.agregar(dim)
        if self.es("="):
            self.consumir("'='")
            d.agregar(self.lista_init() if self.es("{") else self.expresion())
        elif self.es("("):
            d.agregar(self.argumentos())
        elif self.es("{"):
            d.agregar(self.lista_init())
        self.salir()
        return d

    def parametros(self):
        self.entrar("parametros")
        n = self.nodo("Parámetros")
        self.esperar("(")
        if self.es("void") and self.es(")", k=1):
            self.consumir("'void'")
        elif not self.es(")"):
            while True:
                if self.es("..."):
                    n.agregar(self.nodo("Variádico", self.consumir("'...'").lexema))
                    break
                p = self.nodo("Parámetro")
                if not self.es_inicio_tipo():
                    self.error("el tipo del parámetro", SUGERENCIAS["tipo"])
                t = self.tipo()
                t.valor += self.punteros()
                p.agregar(t)
                if self.es_tipo("IDENTIFICADOR"):
                    p.valor = self.consumir("IDENTIFICADOR").lexema
                while self.es("["):
                    self.consumir("'['")
                    if not self.es("]"):
                        self.expresion()
                    self.esperar("]")
                    t.valor += "[]"
                if self.es("="):
                    self.consumir("'='")
                    p.agregar(self.expresion())
                n.agregar(p)
                if not self.es(","):
                    break
                self.consumir("','")
        self.esperar(")")
        self.salir()
        return n

    # ───────────────────────── tipos ─────────────────────────
    def es_inicio_tipo(self, k=0):
        t = self.ver(k)
        return (self.es_reservada(TIPOS_PREDEFINIDOS | {"const", "volatile", "struct", "class",
                                                         "enum", "typename", "union"}, k=k)
                or t.tipo == "IDENTIFICADOR" or self.es("::", k=k))

    def tipo(self):
        self.entrar("tipo")
        n = self.nodo("Tipo")
        partes = []
        while self.es("const", "volatile"):
            partes.append(self.consumir("calificador").lexema)
        if self.es("struct", "class", "enum", "typename", "union"):
            partes.append(self.consumir("palabra de tipo").lexema)
        if self.es_reservada(TIPOS_PREDEFINIDOS):
            while self.es_reservada(TIPOS_PREDEFINIDOS):   # unsigned long long int
                partes.append(self.consumir("tipo").lexema)
        elif self.es_tipo("IDENTIFICADOR") or self.es("::"):
            nombre = ""
            if self.es("::"):
                self.consumir("'::'")
                nombre = "::"
            while True:
                nombre += self.esperar_ident().lexema
                if self.es("<"):
                    nombre += self.args_plantilla()
                if self.es("::") and self.es_tipo("IDENTIFICADOR", k=1):
                    self.consumir("'::'")
                    nombre += "::"
                    continue
                break
            partes.append(nombre)
        else:
            self.error("un tipo", SUGERENCIAS["tipo"])
        while self.es("const"):
            partes.append(self.consumir("'const'").lexema)
        n.valor = " ".join(partes)
        self.salir()
        return n

    def args_plantilla(self):
        """'<' (tipo | constante) {',' ...} '>'   p. ej. map<string, vector<int>>"""
        self.consumir("'<'")
        args = []
        while not self.es(">", ">>") and self.actual.tipo != "EOF":
            if self.actual.tipo in ("ENTERO", "REAL"):
                args.append(self.consumir("constante").lexema)
            else:
                t = self.tipo()
                args.append(t.valor + self.punteros())
            if not self.es(","):
                break
            self.consumir("','")
        if self.es(">>"):
            self.partir_mayor()
        self.esperar(">")
        return "<" + ", ".join(args) + ">"

    def _saltar_tipo(self, k):
        """Lookahead sin consumir: posición tras {especificadores} tipo {*|&}, o -1."""
        while self.es_reservada(ESPECIFICADORES, k=k):
            k += 1
        if self.es("struct", "class", "enum", "typename", k=k):
            k += 1
        if self.es_reservada(TIPOS_PREDEFINIDOS, k=k):
            while self.es_reservada(TIPOS_PREDEFINIDOS, k=k):
                k += 1
        elif self.es_tipo("IDENTIFICADOR", k=k) or self.es("::", k=k):
            if self.es("::", k=k):
                k += 1
            while True:
                if not self.es_tipo("IDENTIFICADOR", k=k):
                    return -1
                k += 1
                if self.es("<", k=k):
                    prof = 0
                    while True:
                        lx = self.ver(k)
                        if lx.tipo == "EOF" or lx.lexema in (";", "{", "}", "(", ")", "=", "&&", "||"):
                            return -1
                        if lx.lexema == "<":
                            prof += 1
                        elif lx.lexema in (">", ">>"):
                            prof -= len(lx.lexema)
                            if prof <= 0:
                                k += 1
                                break
                        k += 1
                if self.es("::", k=k):
                    k += 1
                    continue
                break
        else:
            return -1
        while self.es("const", "*", "&", "&&", k=k):
            k += 1
        return k

    def es_declaracion(self):
        if self.es_reservada(ESPECIFICADORES) or self.es_reservada(TIPOS_PREDEFINIDOS):
            return True
        k = self._saltar_tipo(0)
        return k > 0 and self.es_tipo("IDENTIFICADOR", k=k)

    # ───────────────────────── sentencias ─────────────────────────
    def bloque(self):
        self.entrar("bloque")
        n = self.nodo("Bloque")
        self.esperar("{")
        while not self.es("}") and self.actual.tipo != "EOF":
            antes = self.p
            n.agregar(self.sentencia_segura())
            if self.p == antes:
                self.p += 1
        self.esperar("}")
        self.salir()
        return n

    def sentencia_segura(self):
        nivel = len(self.pila)
        try:
            return self.sentencia()
        except ErrorSintactico:
            del self.pila[nivel:]
            self.sincronizar((";", "}"))
            return None

    def sentencia(self):
        if self.es("{"):
            return self.bloque()
        if self.es(";"):
            n = self.nodo("SentenciaVacía")
            self.consumir("';'")
            return n
        lx = self.actual.lexema if self.actual.tipo == "RESERVADA" else None
        despacho = {"if": self.s_if, "while": self.s_while, "do": self.s_do, "for": self.s_for,
                    "switch": self.s_switch, "return": self.s_return, "break": self.s_salto,
                    "continue": self.s_salto, "try": self.s_try, "throw": self.s_throw}
        if lx in despacho:
            return despacho[lx]()
        if lx in ("using", "typedef", "enum"):
            return {"using": self.s_using, "typedef": self.typedef, "enum": self.enum}[lx]()
        if self.es("class", "struct") and self.es_tipo("IDENTIFICADOR", k=1) and self.es("{", ":", k=2):
            return self.clase()
        if self.es_declaracion():
            self.entrar("decl_local")
            n = self.decl_local()
            self.esperar(";")
            self.salir()
            return n
        self.entrar("expr_sent")
        n = self.nodo("SentenciaExpresión")
        n.agregar(self.expresion())
        self.esperar(";")
        self.salir()
        return n

    def decl_local(self):
        n = self.nodo("DeclaraciónVariable")
        mods = self.especificadores()
        self._mods(n, mods)
        n.agregar(self.tipo())
        n.agregar(self.declarador())
        while self.es(","):
            self.consumir("','")
            n.agregar(self.declarador())
        return n

    def condicion(self, palabra):
        self.esperar("(")
        if self.es(")"):
            self.error("una condición", f"Escribe la condición dentro de {palabra} ( ... ).")
        c = self.nodo("Condición")
        c.agregar(self.expresion())
        self.esperar(")")
        return c

    def s_if(self):
        self.entrar("if")
        n = self.nodo("If")
        self.consumir("'if'")
        n.agregar(self.condicion("if"), self.sentencia_segura())
        if self.es("else"):
            e = self.nodo("Else")
            self.consumir("'else'")
            e.agregar(self.sentencia_segura())
            n.agregar(e)
        self.salir()
        return n

    def s_while(self):
        self.entrar("while")
        n = self.nodo("While")
        self.consumir("'while'")
        n.agregar(self.condicion("while"), self.sentencia_segura())
        self.salir()
        return n

    def s_do(self):
        self.entrar("do")
        n = self.nodo("DoWhile")
        self.consumir("'do'")
        n.agregar(self.sentencia_segura())
        self.esperar("while")
        n.agregar(self.condicion("while"))
        self.esperar(";")
        self.salir()
        return n

    def s_for(self):
        self.entrar("for")
        n = self.nodo("For")
        self.consumir("'for'")
        self.esperar("(")
        ini = self.nodo("Inicialización")
        if not self.es(";"):
            if self.es_declaracion():
                # for basado en rango:  for (int x : v)  /  for (auto& x : v)
                k = self._saltar_tipo(0)
                if self.es(":", k=k + 1):
                    n.tipo = "ForRango"
                    t = self.tipo()
                    t.valor += self.punteros()
                    n.valor = self.esperar_ident().lexema
                    self.consumir("':'")
                    n.agregar(t, self.expresion())
                    self.esperar(")")
                    n.agregar(self.sentencia_segura())
                    self.salir()
                    return n
                ini.agregar(self.decl_local())
            else:
                ini.agregar(self.expresion())
                while self.es(","):
                    self.consumir("','")
                    ini.agregar(self.expresion())
        self.esperar(";")
        cond = self.nodo("Condición")
        if not self.es(";"):
            cond.agregar(self.expresion())
        self.esperar(";")
        inc = self.nodo("Incremento")
        if not self.es(")"):
            inc.agregar(self.expresion())
            while self.es(","):
                self.consumir("','")
                inc.agregar(self.expresion())
        self.esperar(")")
        n.agregar(ini, cond, inc, self.sentencia_segura())
        self.salir()
        return n

    def s_switch(self):
        self.entrar("switch")
        n = self.nodo("Switch")
        self.consumir("'switch'")
        n.agregar(self.condicion("switch"))
        self.esperar("{")
        while self.es("case", "default"):
            sec = self.nodo("Case" if self.es("case") else "Default")
            if self.es("case"):
                self.consumir("'case'")
                sec.agregar(self.expresion())
            else:
                self.consumir("'default'")
            self.esperar(":")
            while not self.es("case", "default", "}") and self.actual.tipo != "EOF":
                antes = self.p
                sec.agregar(self.sentencia_segura())
                if self.p == antes:
                    self.p += 1
            n.agregar(sec)
        self.esperar("}")
        self.salir()
        return n

    def s_return(self):
        self.entrar("return")
        n = self.nodo("Return")
        self.consumir("'return'")
        if not self.es(";"):
            n.agregar(self.lista_init() if self.es("{") else self.expresion())
        self.esperar(";")
        self.salir()
        return n

    def s_salto(self):
        self.entrar("salto")
        n = self.nodo(self.actual.lexema.capitalize())
        self.consumir("'break' o 'continue'")
        self.esperar(";")
        self.salir()
        return n

    def s_try(self):
        self.entrar("try")
        n = self.nodo("Try")
        self.consumir("'try'")
        n.agregar(self.bloque())
        if not self.es("catch"):
            self.error("'catch'", "Todo bloque try necesita al menos un catch (...) { }.")
        while self.es("catch"):
            c = self.nodo("Catch")
            self.consumir("'catch'")
            self.esperar("(")
            if self.es("..."):
                c.valor = self.consumir("'...'").lexema
            else:
                t = self.tipo()
                t.valor += self.punteros()
                c.agregar(t)
                if self.es_tipo("IDENTIFICADOR"):
                    c.valor = self.consumir("IDENTIFICADOR").lexema
            self.esperar(")")
            c.agregar(self.bloque())
            n.agregar(c)
        self.salir()
        return n

    def s_throw(self):
        self.entrar("throw")
        n = self.nodo("Throw")
        self.consumir("'throw'")
        if not self.es(";"):
            n.agregar(self.expresion())
        self.esperar(";")
        self.salir()
        return n

    # ───────────────────────── expresiones ─────────────────────────
    def expresion(self):
        e = self.asignacion()
        return e

    def asignacion(self):
        izq = self.condicional()
        if self.actual.tipo == "OPERADOR" and self.actual.lexema in OPS_ASIGNACION:
            self.entrar("asignacion")
            op = self.consumir("operador de asignación")
            n = Nodo("Asignación", op.lexema, op.linea, op.columna, tok_ini=izq.tok_ini)
            n.agregar(izq, self.lista_init() if self.es("{") else self.asignacion())
            self.salir()
            return n
        return izq

    def condicional(self):
        c = self.binaria(0)
        if self.es("?"):
            self.entrar("condicional")
            q = self.consumir("'?'")
            n = Nodo("Ternario", "?:", q.linea, q.columna, tok_ini=c.tok_ini)
            si = self.expresion()
            self.esperar(":")
            n.agregar(c, si, self.asignacion())
            self.salir()
            return n
        return c

    NIVELES = [("||", "or"), ("&&", "and"), ("|", "bitor"), ("^", "xor"), ("&", "bitand"),
               ("==", "!=", "not_eq"), ("<", ">", "<=", ">=", "<=>"), ("<<", ">>"),
               ("+", "-"), ("*", "/", "%")]

    def binaria(self, nivel):
        if nivel == len(self.NIVELES):
            return self.unaria()
        izq = self.binaria(nivel + 1)
        while self.actual.tipo in ("OPERADOR", "RESERVADA") and self.actual.lexema in self.NIVELES[nivel]:
            self.entrar("binaria")
            op = self.consumir("operador")
            der = self.binaria(nivel + 1)
            izq = Nodo("Binaria", op.lexema, op.linea, op.columna, tok_ini=izq.tok_ini).agregar(izq, der)
            self.salir()
        return izq

    def unaria(self):
        t = self.actual
        if (t.tipo == "OPERADOR" and t.lexema in ("!", "~", "-", "+", "++", "--", "*", "&")) \
                or self.es_reservada({"not", "compl"}):
            self.entrar("unaria")
            nombres = {"*": "Desreferencia", "&": "Dirección"}
            n = self.nodo(nombres.get(t.lexema, "Unaria"))
            n.valor = self.consumir("operador unario").lexema
            n.agregar(self.unaria())
            self.salir()
            return n
        if self.es("sizeof"):
            self.entrar("unaria")
            n = self.nodo("Sizeof")
            self.consumir("'sizeof'")
            if self.es("(") and self._saltar_tipo(1) > 0 and self.es(")", k=self._saltar_tipo(1)):
                self.consumir("'('")
                n.agregar(self.tipo())
                self.punteros()
                self.esperar(")")
            else:
                n.agregar(self.unaria())
            self.salir()
            return n
        if self.es("delete"):
            self.entrar("unaria")
            n = self.nodo("Delete")
            self.consumir("'delete'")
            if self.es("[") and self.es("]", k=1):
                self.consumir("'['")
                self.consumir("']'")
                n.valor = "[]"
            n.agregar(self.unaria())
            self.salir()
            return n
        # conversión estilo C:  (int) x   (double*) p
        if self.es("(") and self.es_reservada(TIPOS_PREDEFINIDOS, k=1):
            k = self._saltar_tipo(1)
            if k > 0 and self.es(")", k=k):
                self.entrar("unaria")
                n = self.nodo("Conversión")
                self.consumir("'('")
                t = self.tipo()
                n.valor = t.valor + self.punteros()
                self.consumir("')'")
                n.agregar(self.unaria())
                self.salir()
                return n
        return self.postfija()

    def postfija(self):
        e = self.primaria()
        while True:
            if self.es(".", "->"):
                self.entrar("postfija")
                op = self.consumir("'.' o '->'").lexema
                m = self.esperar_ident()
                e = Nodo("AccesoMiembro" if op == "." else "AccesoPuntero", m.lexema, m.linea, m.columna,
                         tok_ini=e.tok_ini).agregar(e)
                self.salir()
            elif self.es("("):
                self.entrar("llamada")
                n = Nodo("Llamada", e.valor if e.tipo in ("Identificador", "AccesoMiembro", "AccesoPuntero") else "",
                         e.linea, e.columna, tok_ini=e.tok_ini)
                n.agregar(e, self.argumentos())
                e = n
                self.salir()
            elif self.es("["):
                self.entrar("postfija")
                self.consumir("'['")
                n = Nodo("Índice", "", e.linea, e.columna, tok_ini=e.tok_ini)
                n.agregar(e, self.expresion())
                self.esperar("]")
                e = n
                self.salir()
            elif self.es("++", "--"):
                self.entrar("postfija")
                op = self.consumir("operador")
                e = Nodo("Postfijo", op.lexema, op.linea, op.columna, tok_ini=e.tok_ini).agregar(e)
                self.salir()
            else:
                return e

    def argumentos(self):
        self.entrar("argumentos")
        n = self.nodo("Argumentos")
        self.esperar("(")
        if not self.es(")"):
            while True:
                n.agregar(self.lista_init() if self.es("{") else self.asignacion())
                if not self.es(","):
                    break
                self.consumir("','")
        self.esperar(")")
        self.salir()
        return n

    def lista_init(self):
        self.entrar("lista")
        n = self.nodo("ListaInicialización")
        self.esperar("{")
        while not self.es("}") and self.actual.tipo != "EOF":
            n.agregar(self.lista_init() if self.es("{") else self.asignacion())
            if not self.es(","):
                break
            self.consumir("','")
        self.esperar("}")
        self.salir()
        return n

    def primaria(self):
        self.entrar("primaria")
        t = self.actual
        if t.tipo in ("ENTERO", "REAL", "CADENA", "CARACTER"):
            tipo = {"ENTERO": "LiteralEntero", "REAL": "LiteralFlotante",
                    "CADENA": "LiteralCadena", "CARACTER": "LiteralCarácter"}[t.tipo]
            n = self.nodo(tipo, t.lexema)
            self.consumir("literal")
            while self.es_tipo("CADENA"):        # "hola " "mundo"
                n.valor += " " + self.consumir("literal").lexema
        elif self.es("true", "false"):
            n = self.nodo("LiteralBooleano", t.lexema)
            self.consumir("literal")
        elif self.es("nullptr", "NULL"):
            n = self.nodo("LiteralNulo", t.lexema)
            self.consumir("literal")
        elif self.es("this"):
            n = self.nodo("This", "this")
            self.consumir("'this'")
        elif t.tipo == "IDENTIFICADOR" or self.es("::"):
            n = self.nodo("Identificador")
            n.valor, _ = self.nombre_calificado()
        elif self.es_reservada(CASTS):            # static_cast<int>(x)
            n = self.nodo("Conversión", self.consumir("conversión").lexema)
            self.esperar("<")
            t2 = self.tipo()
            t2.valor += self.punteros()
            if self.es(">>"):
                self.partir_mayor()
            self.esperar(">")
            self.esperar("(")
            n.agregar(t2, self.expresion())
            self.esperar(")")
        elif self.es_reservada(TIPOS_PREDEFINIDOS) and self.es("(", "{", k=1):
            n = self.nodo("ConversiónFuncional", self.consumir("tipo").lexema)   # int(x)
            n.agregar(self.argumentos() if self.es("(") else self.lista_init())
        elif self.es("("):
            self.consumir("'('")
            n = self.expresion()
            self.esperar(")")
        elif self.es("new"):
            self.salir()
            return self.creacion()
        elif self.es("["):
            self.error("una expresión", "Las expresiones lambda no están soportadas en este analizador.")
        else:
            self.error("una expresión", SUGERENCIAS["expresión"])
        self.salir()
        return n

    def creacion(self):
        self.entrar("new")
        n = self.nodo("New")
        self.consumir("'new'")
        t = self.tipo()
        n.valor = t.valor + self.punteros()
        n.agregar(t)
        if self.es("["):
            n.tipo = "NewArreglo"
            self.consumir("'['")
            n.agregar(self.expresion())
            self.esperar("]")
        if self.es("("):
            n.agregar(self.argumentos())
        elif self.es("{"):
            n.agregar(self.lista_init())
        self.salir()
        return n


def analizar(tokens) -> ResultadoSintactico:
    p = Parser(tokens)
    try:
        arbol = p.programa()
    except OverflowError:
        arbol = Nodo("Programa", "(análisis detenido: demasiados errores)")
        p.pila.clear()
    return ResultadoSintactico(arbol, p.errores, p.pasos, list(arbol.preorden()))


if __name__ == "__main__":
    import sys
    from lexico import analizar as lex
    codigo = open(sys.argv[1], encoding="utf-8").read() if len(sys.argv) > 1 else sys.stdin.read()
    toks, errs = lex(codigo)
    r = analizar(toks)
    print(r.arbol.como_texto())
    for e in errs + r.errores:
        print(f"[{e['fase']}] {e['linea']}:{e['columna']}  {e['mensaje']}")
