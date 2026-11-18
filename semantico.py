# -*- coding: utf-8 -*-
"""
Analizador SEMÁNTICO de C++ (trabaja sobre el árbol que entrega sintactico.py).

Contrato con la interfaz (ver LEEME.md):

    analizar(arbol, tokens) -> dict
        "simbolos"  list[dict]  nombre, categoria, tipo, ambito, linea
        "errores"   list[dict]  fase, mensaje, linea, columna, sugerencia,
                                esperado, encontrado, regla
        "pasos"     list[dict]  traza para la animación paso a paso; un paso
                                con "simbolo" agrega esa fila a la tabla

Cómo trabaja
------------
Recorre el árbol en el orden en que está escrito el programa, igual que un
compilador de una sola pasada. Cada declaración se guarda en la tabla de
símbolos del ámbito donde aparece (global, espacio de nombres, clase, función
o bloque) y cada nombre que se usa se busca desde el ámbito más interno hacia
afuera. Al mismo tiempo se calcula el tipo de cada expresión para revisar que
asignaciones, operaciones, llamadas y returns tengan sentido.

Las clases se revisan en dos pasadas: primero se registran todos sus miembros
y después se analizan los cuerpos de los métodos, porque en C++ un método puede
usar atributos que están declarados más abajo dentro de la misma clase.

Cuando el tipo de algo no se puede saber (por ejemplo, lo que devuelve una
función poco común de la biblioteca) se marca como «desconocido» y se acepta en
cualquier lugar. Así se evitan errores en cascada y falsos positivos.

Verificaciones
--------------
  Nombres     identificadores, funciones y tipos declarados antes de usarse;
              redeclaraciones en el mismo ámbito; cout, string, vector... sin
              std o sin su #include.
  Tipos       inicialización y asignación compatibles; operadores con tipos
              válidos (%, +, comparaciones, lógicos, <<, >>); condiciones que
              se puedan evaluar como verdadero/falso; conversiones imposibles;
              pérdida de datos dentro de llaves (narrowing).
  Funciones   número y tipo de argumentos (con sobrecarga y valores por
              defecto); return con el tipo correcto; funciones sin return;
              redefiniciones; prototipos que no coinciden; main.
  Variables   constantes que se modifican o no se inicializan; referencias;
              asignar a algo que no es variable; arreglos (tamaño, índice
              constante fuera de rango, demasiados valores, copia con '=').
  Clases      miembros inexistentes; acceso a private/protected; '.' contra
              '->'; constructores; métodos const; clases abstractas; métodos
              definidos fuera de la clase; override.
  Control     break y continue fuera de ciclos; switch con double o string;
              case repetidos o no constantes; división entre cero constante.
"""
import difflib
import math
import os
import re
from dataclasses import dataclass, field, replace

DEPURAR = bool(os.environ.get("SEMANTICO_DEPURAR"))   # 1 = no ocultar excepciones internas


# ═══════════════════════════════ tipos ═══════════════════════════════

ENTEROS = {
    "char", "unsigned char", "short", "unsigned short", "int", "unsigned int", "long",
    "unsigned long", "long long", "unsigned long long", "wchar_t", "char8_t", "char16_t",
    "char32_t", "size_t", "ssize_t", "ptrdiff_t", "int8_t", "int16_t", "int32_t", "int64_t",
    "uint8_t", "uint16_t", "uint32_t", "uint64_t", "intptr_t", "uintptr_t", "time_t",
    "clock_t", "streamsize",
}
REALES = {"float", "double", "long double"}
BASICOS = ENTEROS | REALES | {"bool", "void", "auto"}
PALABRAS_TIPO = {"void", "bool", "char", "wchar_t", "char8_t", "char16_t", "char32_t", "short",
                 "int", "long", "float", "double", "signed", "unsigned", "auto"}
DESCARTAR = {"const", "volatile", "struct", "class", "enum", "typename", "union", "mutable",
             "static", "constexpr", "inline", "register", "extern", "thread_local"}

CADENAS = {"string", "wstring", "string_view", "u16string", "u32string"}
FLUJOS_SALIDA = {"ostream", "ofstream", "ostringstream"}
FLUJOS_ENTRADA = {"istream", "ifstream", "istringstream"}
FLUJOS_AMBOS = {"iostream", "fstream", "stringstream"}
FLUJOS = FLUJOS_SALIDA | FLUJOS_ENTRADA | FLUJOS_AMBOS
CONTENEDORES = {"vector", "map", "unordered_map", "set", "unordered_set", "multimap", "multiset",
                "list", "deque", "queue", "priority_queue", "stack", "array", "pair", "tuple",
                "bitset", "initializer_list", "optional"}
SECUENCIAS = {"vector", "deque", "array", "list", "set", "unordered_set", "multiset",
              "initializer_list"}
OTROS_STD = {"exception", "runtime_error", "logic_error", "invalid_argument", "out_of_range",
             "length_error", "overflow_error", "underflow_error", "domain_error", "range_error",
             "bad_alloc", "thread", "mutex", "lock_guard", "unique_lock", "condition_variable",
             "atomic", "future", "promise", "random_device", "mt19937", "mt19937_64",
             "default_random_engine", "uniform_int_distribution", "uniform_real_distribution",
             "normal_distribution", "any", "function", "variant", "complex", "unique_ptr",
             "shared_ptr", "weak_ptr", "regex", "smatch", "cmatch", "numeric_limits",
             "istream_iterator", "ostream_iterator", "ios", "streambuf", "locale", "byte"}
SIN_STD = {"FILE", "tm"}
TIPOS_BIBLIOTECA = CADENAS | FLUJOS | CONTENEDORES | OTROS_STD | SIN_STD

# categorías de tipo que usa el analizador
NUMERICAS = {"entero", "real", "bool", "enum_simple"}
ENTERAS = {"entero", "bool", "enum_simple"}
PUNTEROS = {"puntero", "arreglo"}
LIBRES = {"?", "std"}                     # tipos que no se pueden revisar: se aceptan
COMPARACIONES = {"==", "!=", "<", ">", "<=", ">=", "<=>", "not_eq"}
LOGICOS = {"&&", "||", "and", "or"}
CASTS = {"static_cast", "dynamic_cast", "const_cast", "reinterpret_cast"}


@dataclass(frozen=True)
class Tipo:
    nombre: str                  # tipo base: int, double, string, vector<int>, Cuenta, ? ...
    punteros: int = 0
    ref: bool = False
    const: bool = False          # el objeto es constante (const int x / int* const p)
    const_base: bool = False     # lo apuntado es constante (const int* p)
    dims: tuple = ()             # dimensiones de arreglo (None = no se conoce)

    def __str__(self):
        if self.nombre == "?":
            return "desconocido"
        if self.nombre == "{}":
            return "lista { }"
        if self.nombre == "<función>":
            return "función"
        s = self.nombre
        if self.punteros:
            s = ("const " if self.const_base else "") + s + "*" * self.punteros + (" const" if self.const else "")
        elif self.const:
            s = "const " + s
        if self.dims:
            s += "".join(f"[{'' if d is None else d}]" for d in self.dims)
        if self.ref:
            s += "&"
        return s


DESCONOCIDO = Tipo("?")
LISTA = Tipo("{}")
FUNCION = Tipo("<función>")
VOID, INT, LONG = Tipo("void"), Tipo("int"), Tipo("long")
FLOAT, DOUBLE, BOOL, CHAR = Tipo("float"), Tipo("double"), Tipo("bool"), Tipo("char")
SIZE_T, STRING = Tipo("size_t"), Tipo("string")
CSTR = Tipo("char", punteros=1, const_base=True)      # tipo de un literal "texto"
NULO = Tipo("nullptr_t")


def limpio(nombre):
    return re.sub(r"\bstd::", "", nombre or "")


def base(nombre):
    return limpio(nombre).split("<")[0].strip()


def dividir_palabras(s):
    """Separa por espacios sin romper los argumentos de plantilla: map<string, int>."""
    partes, prof, act = [], 0, ""
    for c in s:
        if c == "<":
            prof += 1
        elif c == ">":
            prof -= 1
        if c.isspace() and prof == 0:
            if act:
                partes.append(act)
            act = ""
        else:
            act += c
    if act:
        partes.append(act)
    return partes


def args_plantilla(nombre):
    """'map<string, vector<int>>' → ['string', 'vector<int>']"""
    if "<" not in nombre or not nombre.rstrip().endswith(">"):
        return []
    interior = nombre[nombre.index("<") + 1:nombre.rstrip().rindex(">")]
    partes, prof, act = [], 0, ""
    for c in interior:
        if c == "<":
            prof += 1
        elif c == ">":
            prof -= 1
        if c == "," and prof == 0:
            partes.append(act.strip())
            act = ""
        else:
            act += c
    if act.strip():
        partes.append(act.strip())
    return partes


def normalizar_basico(palabras):
    p = list(palabras)
    sin_signo = "unsigned" in p
    p = [x for x in p if x not in ("unsigned", "signed")]
    if "int" in p and len(p) > 1:
        p.remove("int")
    nombre = " ".join(p) if p else "int"
    if sin_signo and nombre in ("char", "short", "int", "long", "long long"):
        nombre = "unsigned " + nombre
    return nombre


def texto_a_tipo(texto):
    """Convierte el texto de un nodo Tipo ('const vector<int>&', 'char*', 'unsigned long') en Tipo."""
    s = (texto or "").strip()
    if s.startswith("::"):
        s = s[2:]
    punteros, ref, const_ptr = 0, False, False
    while True:
        s = s.rstrip()
        if s.endswith("&&"):
            ref, s = True, s[:-2]
        elif s.endswith("&"):
            ref, s = True, s[:-1]
        elif s.endswith("[]"):
            punteros, s = punteros + 1, s[:-2]
        elif s.endswith("*"):
            punteros, s = punteros + 1, s[:-1]
        elif re.search(r"\*\s*const$", s):
            const_ptr, s = True, s[:-5]
        else:
            break
    palabras = dividir_palabras(s)
    const = "const" in palabras
    palabras = [p for p in palabras if p not in DESCARTAR]
    if not palabras:
        nombre = "?"
    elif all(p in PALABRAS_TIPO for p in palabras):
        nombre = normalizar_basico(palabras)
    else:
        nombre = " ".join(palabras)
    if punteros:
        return Tipo(nombre, punteros, ref, const_ptr, const)
    return Tipo(nombre, 0, ref, const or const_ptr)


def niveles(t):
    return t.punteros + len(t.dims)


def decaer(t):
    """Un arreglo usado como valor se convierte en puntero a su primer elemento."""
    if not t.dims:
        return replace(t, ref=False)
    return Tipo(t.nombre, t.punteros + len(t.dims), const_base=t.const if not t.punteros else t.const_base)


def elemento(t):
    """Tipo de t[i] o de *t."""
    if t.dims:
        return replace(t, dims=t.dims[1:], ref=False)
    if t.punteros:
        if t.punteros == 1:
            return Tipo(t.nombre, 0, const=t.const_base)
        return Tipo(t.nombre, t.punteros - 1, const_base=t.const_base)
    return DESCONOCIDO


def sin_cv(t):
    return replace(t, ref=False, const=False)


def es_texto_c(t):
    return t.nombre in ("char", "wchar_t") and niveles(t) == 1


def es_char(t):
    return t.nombre == "char" and niveles(t) == 0


def entero_literal(txt):
    s = (txt or "").replace("'", "").rstrip("uUlLzZ")
    try:
        if s.lower().startswith(("0x", "0b")):
            return int(s, 0)
        if len(s) > 1 and s.startswith("0") and s.isdigit():
            return int(s, 8)
        return int(s)
    except ValueError:
        return None


def real_literal(txt):
    try:
        return float((txt or "").replace("'", "").rstrip("fFlL"))
    except ValueError:
        return None


def caracter_literal(txt):
    m = re.fullmatch(r"(?:u8|u|U|L)?'(.*)'", txt or "", re.S)
    if not m:
        return None
    c = m.group(1)
    esc = {"n": 10, "t": 9, "0": 0, "\\": 92, "'": 39, '"': 34, "r": 13, "a": 7, "b": 8, "f": 12, "v": 11}
    if len(c) == 1:
        return ord(c)
    if len(c) == 2 and c[0] == "\\" and c[1] in esc:
        return esc[c[1]]
    return None


def largo_cadena(txt):
    """Caracteres que ocupa un literal "..." contando el '\\0' final (None si no se puede saber)."""
    partes = re.findall(r'(u8|u|U|L|R)?"((?:\\.|[^"\\])*)"', txt or "")
    if not partes or any(p for p, _ in partes):
        return None
    total = sum(len(re.sub(r"\\(x[0-9a-fA-F]+|[0-7]{1,3}|.)", "_", c)) for _, c in partes)
    return total + 1


def plural(n, palabra):
    return f"{n} {palabra}" + ("" if n == 1 else "s")


def cuantos_txt(mn, mx):
    if mx is None:
        return f"al menos {plural(mn, 'argumento')}"
    if mn == mx:
        return "ningún argumento" if mn == 0 else plural(mn, "argumento")
    return f"entre {mn} y {mx} argumentos"


ARTICULOS = {
    "variable": "una variable", "parámetro": "un parámetro", "atributo": "un atributo",
    "función": "una función", "método": "un método", "macro": "una constante #define",
    "enumerador": "un valor de enumeración", "clase": "una clase", "struct": "un struct",
    "unión": "una unión", "enumeración": "una enumeración", "alias": "un alias de tipo",
    "espacio de nombres": "un espacio de nombres", "constructor": "un constructor",
    "parámetro de plantilla": "un parámetro de plantilla", "destructor": "un destructor",
}


def art(categoria):
    return ARTICULOS.get(categoria, categoria)


def cap(s):
    return s[:1].upper() + s[1:]


def de(sujeto):
    """'de' + sujeto, con contracción: 'del constructor de X', 'de 'sumar''."""
    return "del " + sujeto[3:] if sujeto.startswith("el ") else "de " + sujeto


# ═══════════════════════════ biblioteca estándar ═══════════════════════════
# nombre: (tipo de retorno, mínimo de argumentos, máximo (None = sin límite),
#          ¿necesita std?, clase de argumentos: num = números, cad = string, cstr = char*)
FUNCIONES_BIBLIOTECA = {
    "printf": ("int", 1, None, False, None), "scanf": ("int", 1, None, False, None),
    "puts": ("int", 1, 1, False, None), "putchar": ("int", 1, 1, False, None),
    "getchar": ("int", 0, 0, False, None), "getch": ("int", 0, 0, False, None),
    "sprintf": ("int", 2, None, False, None), "fprintf": ("int", 2, None, False, None),
    "fscanf": ("int", 2, None, False, None), "fopen": ("FILE*", 2, 2, False, None),
    "fclose": ("int", 1, 1, False, None), "fgets": ("char*", 3, 3, False, None),
    "sqrt": ("double", 1, 1, False, "num"), "cbrt": ("double", 1, 1, False, "num"),
    "pow": ("double", 2, 2, False, "num"), "fabs": ("double", 1, 1, False, "num"),
    "abs": ("int", 1, 1, False, "num"), "labs": ("long", 1, 1, False, "num"),
    "floor": ("double", 1, 1, False, "num"), "ceil": ("double", 1, 1, False, "num"),
    "round": ("double", 1, 1, False, "num"), "trunc": ("double", 1, 1, False, "num"),
    "sin": ("double", 1, 1, False, "num"), "cos": ("double", 1, 1, False, "num"),
    "tan": ("double", 1, 1, False, "num"), "asin": ("double", 1, 1, False, "num"),
    "acos": ("double", 1, 1, False, "num"), "atan": ("double", 1, 1, False, "num"),
    "atan2": ("double", 2, 2, False, "num"), "exp": ("double", 1, 1, False, "num"),
    "log": ("double", 1, 1, False, "num"), "log10": ("double", 1, 1, False, "num"),
    "log2": ("double", 1, 1, False, "num"), "fmod": ("double", 2, 2, False, "num"),
    "hypot": ("double", 2, 3, False, "num"),
    "rand": ("int", 0, 0, False, None), "srand": ("void", 1, 1, False, "num"),
    "time": ("time_t", 1, 1, False, None), "clock": ("clock_t", 0, 0, False, None),
    "exit": ("void", 1, 1, False, "num"), "abort": ("void", 0, 0, False, None),
    "system": ("int", 1, 1, False, "cstr"), "atoi": ("int", 1, 1, False, "cstr"),
    "atof": ("double", 1, 1, False, "cstr"), "atol": ("long", 1, 1, False, "cstr"),
    "strlen": ("size_t", 1, 1, False, "cstr"), "strcpy": ("char*", 2, 2, False, "cstr"),
    "strncpy": ("char*", 3, 3, False, None), "strcat": ("char*", 2, 2, False, "cstr"),
    "strcmp": ("int", 2, 2, False, "cstr"), "strncmp": ("int", 3, 3, False, None),
    "strchr": ("char*", 2, 2, False, None), "strstr": ("char*", 2, 2, False, "cstr"),
    "memset": ("void*", 3, 3, False, None), "memcpy": ("void*", 3, 3, False, None),
    "malloc": ("void*", 1, 1, False, "num"), "calloc": ("void*", 2, 2, False, "num"),
    "realloc": ("void*", 2, 2, False, None), "free": ("void", 1, 1, False, None),
    "isdigit": ("int", 1, 1, False, "num"), "isalpha": ("int", 1, 1, False, "num"),
    "isalnum": ("int", 1, 1, False, "num"), "isspace": ("int", 1, 1, False, "num"),
    "isupper": ("int", 1, 1, False, "num"), "islower": ("int", 1, 1, False, "num"),
    "ispunct": ("int", 1, 1, False, "num"), "toupper": ("int", 1, 1, False, "num"),
    "tolower": ("int", 1, 1, False, "num"), "assert": ("void", 1, 1, False, None),
    # biblioteca de C++ (espacio de nombres std)
    "to_string": ("string", 1, 1, True, "num"), "stoi": ("int", 1, 3, True, "cad"),
    "stol": ("long", 1, 3, True, "cad"), "stoll": ("long long", 1, 3, True, "cad"),
    "stoul": ("unsigned long", 1, 3, True, "cad"), "stof": ("float", 1, 2, True, "cad"),
    "stod": ("double", 1, 2, True, "cad"), "getline": ("?", 2, 3, True, None),
    "swap": ("void", 2, 2, True, None), "sort": ("void", 2, 3, True, None),
    "stable_sort": ("void", 2, 3, True, None), "reverse": ("void", 2, 2, True, None),
    "max": ("?", 1, 3, True, None), "min": ("?", 1, 3, True, None),
    "find": ("?", 3, 3, True, None), "find_if": ("?", 3, 3, True, None),
    "count": ("?", 3, 3, True, None), "count_if": ("?", 3, 3, True, None),
    "accumulate": ("?", 3, 4, True, None), "fill": ("void", 3, 3, True, None),
    "copy": ("?", 3, 3, True, None), "unique": ("?", 2, 3, True, None),
    "max_element": ("?", 2, 3, True, None), "min_element": ("?", 2, 3, True, None),
    "lower_bound": ("?", 3, 4, True, None), "upper_bound": ("?", 3, 4, True, None),
    "binary_search": ("bool", 3, 4, True, None), "transform": ("?", 4, 5, True, None),
    "for_each": ("?", 3, 3, True, None), "all_of": ("bool", 3, 3, True, None),
    "any_of": ("bool", 3, 3, True, None), "none_of": ("bool", 3, 3, True, None),
    "iota": ("void", 3, 3, True, None), "distance": ("?", 2, 2, True, None),
    "advance": ("void", 2, 2, True, None), "next": ("?", 1, 2, True, None),
    "prev": ("?", 1, 2, True, None), "make_pair": ("?", 2, 2, True, None),
    "make_tuple": ("?", 0, None, True, None), "tie": ("?", 1, None, True, None),
    "get": ("?", 1, 1, True, None), "move": ("?", 1, 1, True, None),
    "make_unique": ("?", 0, None, True, None), "make_shared": ("?", 0, None, True, None),
    "begin": ("?", 1, 1, True, None), "end": ("?", 1, 1, True, None),
    "setw": ("?", 1, 1, True, "num"), "setprecision": ("?", 1, 1, True, "num"),
    "setfill": ("?", 1, 1, True, None),
}
OBJETOS_BIBLIOTECA = {
    "cout": ("ostream", True), "cerr": ("ostream", True), "clog": ("ostream", True),
    "cin": ("istream", True), "endl": ("?", True), "ends": ("?", True), "flush": ("?", True),
    "ws": ("?", True), "fixed": ("?", True), "scientific": ("?", True), "boolalpha": ("?", True),
    "noboolalpha": ("?", True), "left": ("?", True), "right": ("?", True),
    "showpoint": ("?", True), "hex": ("?", True), "dec": ("?", True), "oct": ("?", True),
    "INT_MAX": ("int", False), "INT_MIN": ("int", False), "LONG_MAX": ("long", False),
    "LONG_MIN": ("long", False), "LLONG_MAX": ("long long", False), "LLONG_MIN": ("long long", False),
    "UINT_MAX": ("unsigned int", False), "SHRT_MAX": ("int", False), "CHAR_MAX": ("int", False),
    "SIZE_MAX": ("size_t", False), "RAND_MAX": ("int", False), "EOF": ("int", False),
    "EXIT_SUCCESS": ("int", False), "EXIT_FAILURE": ("int", False), "DBL_MAX": ("double", False),
    "DBL_MIN": ("double", False), "FLT_MAX": ("float", False), "FLT_MIN": ("float", False),
    "M_PI": ("double", False), "M_E": ("double", False), "CLOCKS_PER_SEC": ("long", False),
    "stdin": ("FILE*", False), "stdout": ("FILE*", False), "stderr": ("FILE*", False),
}
# nombre → (cabecera sugerida, otras cabeceras que también lo declaran)
CABECERAS = {
    "cout": ("iostream",), "cin": ("iostream",), "cerr": ("iostream",), "clog": ("iostream",),
    "vector": ("vector", "queue"), "map": ("map",), "multimap": ("map",), "set": ("set",),
    "multiset": ("set",), "unordered_map": ("unordered_map",),
    "unordered_set": ("unordered_set",), "list": ("list",), "deque": ("deque", "queue", "stack"),
    "stack": ("stack",), "queue": ("queue",), "priority_queue": ("queue",),
    "setw": ("iomanip",), "setprecision": ("iomanip",), "setfill": ("iomanip",),
}
EJEMPLOS = {
    "pow": "pow(base, exponente)", "sqrt": "sqrt(x)", "to_string": "to_string(numero)",
    "stoi": 'stoi("123")', "stod": 'stod("3.5")', "getline": "getline(cin, texto)",
    "swap": "swap(a, b)", "max": "max(a, b)", "min": "min(a, b)", "rand": "rand() % 10",
    "srand": "srand(time(0))", "strlen": "strlen(texto)", "strcmp": "strcmp(a, b)",
    "abs": "abs(x)", "fabs": "fabs(x)", "sort": "sort(v.begin(), v.end())",
}
# métodos: nombre → (retorno, mínimo, máximo, ¿modifica el objeto?)   E = elemento
METODOS_STRING = {
    "size": ("size_t", 0, 0, False), "length": ("size_t", 0, 0, False),
    "empty": ("bool", 0, 0, False), "clear": ("void", 0, 0, True),
    "substr": ("string", 0, 2, False), "find": ("size_t", 1, 3, False),
    "rfind": ("size_t", 1, 3, False), "find_first_of": ("size_t", 1, 3, False),
    "find_last_of": ("size_t", 1, 3, False), "find_first_not_of": ("size_t", 1, 3, False),
    "find_last_not_of": ("size_t", 1, 3, False), "append": ("string&", 1, 4, True),
    "push_back": ("void", 1, 1, True), "pop_back": ("void", 0, 0, True),
    "at": ("char&", 1, 1, False), "front": ("char&", 0, 0, False), "back": ("char&", 0, 0, False),
    "c_str": ("const char*", 0, 0, False), "data": ("const char*", 0, 0, False),
    "insert": ("string&", 2, 4, True), "erase": ("string&", 0, 2, True),
    "replace": ("string&", 3, 5, True), "compare": ("int", 1, 5, False),
    "begin": ("?", 0, 0, False), "end": ("?", 0, 0, False), "rbegin": ("?", 0, 0, False),
    "rend": ("?", 0, 0, False), "cbegin": ("?", 0, 0, False), "cend": ("?", 0, 0, False),
    "resize": ("void", 1, 2, True), "reserve": ("void", 0, 1, True),
    "capacity": ("size_t", 0, 0, False), "swap": ("void", 1, 1, True),
    "assign": ("string&", 1, 4, True), "copy": ("size_t", 2, 3, False),
    "max_size": ("size_t", 0, 0, False), "shrink_to_fit": ("void", 0, 0, True),
    "starts_with": ("bool", 1, 1, False), "ends_with": ("bool", 1, 1, False),
    "contains": ("bool", 1, 1, False),
}
METODOS_VECTOR = {
    "size": ("size_t", 0, 0, False), "empty": ("bool", 0, 0, False), "clear": ("void", 0, 0, True),
    "push_back": ("void", 1, 1, True), "emplace_back": ("void", 0, None, True),
    "pop_back": ("void", 0, 0, True), "at": ("E&", 1, 1, False), "front": ("E&", 0, 0, False),
    "back": ("E&", 0, 0, False), "data": ("?", 0, 0, False), "begin": ("?", 0, 0, False),
    "end": ("?", 0, 0, False), "rbegin": ("?", 0, 0, False), "rend": ("?", 0, 0, False),
    "cbegin": ("?", 0, 0, False), "cend": ("?", 0, 0, False), "insert": ("?", 2, 3, True),
    "emplace": ("?", 1, None, True), "erase": ("?", 1, 2, True), "resize": ("void", 1, 2, True),
    "reserve": ("void", 1, 1, True), "capacity": ("size_t", 0, 0, False),
    "shrink_to_fit": ("void", 0, 0, True), "swap": ("void", 1, 1, True),
    "assign": ("void", 1, 2, True), "max_size": ("size_t", 0, 0, False),
}


# ═══════════════════════════ tabla de símbolos ═══════════════════════════

@dataclass(eq=False)
class Param:
    nombre: str
    tipo: Tipo
    defecto: object = None
    nodo: object = None


@dataclass(eq=False)
class Simbolo:
    nombre: str
    categoria: str
    tipo: Tipo = DESCONOCIDO
    linea: int = 0
    columna: int = 0
    ambito: str = "global"
    params: list = None
    variadico: bool = False
    definida: bool = False
    clase: str = ""
    acceso: str = "public"
    metodo_const: bool = False
    estatico: bool = False
    virtual: bool = False
    virtual_pura: bool = False
    explicito: bool = False
    borrado: bool = False
    es_tipo: bool = False
    valor: object = None
    lib: tuple = None
    extra: str = ""


@dataclass(eq=False)
class InfoClase:
    nombre: str
    clave: str
    linea: int
    bases: list = field(default_factory=list)
    miembros: dict = field(default_factory=dict)
    constructores: list = field(default_factory=list)
    destructor: object = None
    puras: set = field(default_factory=set)
    amigos: set = field(default_factory=set)
    inits: list = field(default_factory=list)
    completa: bool = False
    plantilla: bool = False


@dataclass(eq=False)
class Ambito:
    nombre: str          # ruta completa: "main › for"
    corto: str           # lo que se muestra en la pila: "for"
    tipo: str            # global, espacio, clase, funcion, bloque
    tabla: dict = field(default_factory=dict)
    clase: object = None


@dataclass(eq=False)
class Contexto:
    funcion: object = None
    clase: object = None
    const: bool = False
    estatico: bool = False
    retornos: int = 0


# ═══════════════════════════ analizador ═══════════════════════════

class Analizador:
    MAX_ERRORES = 60

    def __init__(self, arbol, tokens):
        self.arbol = arbol
        self.toks = [t for t in (tokens or []) if getattr(t, "tipo", "") != "EOF"]
        self.indice_tok = {(t.linea, t.columna): i for i, t in enumerate(self.toks)}
        self.errores, self.pasos, self.tabla = [], [], []
        self.global_ = Ambito("global", "global", "global")
        self.pila = [self.global_]
        self.plantillas = []
        self.clases, self.enums, self.enumeradores, self.espacios = {}, {}, {}, {}
        self.espacios_usados = set()
        self.std, self.std_nombres = False, set()
        self.cabeceras, self.cabeceras_locales = set(), False
        self.ctx = None
        self.ciclos = self.switches = 0
        self.reportados = set()
        self.ops_globales = {}
        self.tipos = {}

    # ─────────────────────── utilidades del árbol ───────────────────────
    @staticmethod
    def hijo(n, tipo):
        return next((h for h in n.hijos if h.tipo == tipo), None) if n is not None else None

    @staticmethod
    def hijos(n, tipo):
        return [h for h in n.hijos if h.tipo == tipo] if n is not None else []

    def especificadores(self, n):
        e = self.hijo(n, "Especificadores")
        return set(e.valor.split()) if e is not None else set()

    # ─────────────────────── posiciones y texto ───────────────────────
    @staticmethod
    def _balance(t, solo_llaves=False):
        if t.tipo in ("CADENA", "CARACTER"):
            return 0
        tabla = {"{": 1, "}": -1} if solo_llaves else {"(": 1, "[": 1, "{": 1, ")": -1, "]": -1, "}": -1}
        return tabla.get(t.lexema, 0)

    def _indices(self, nodo):
        i = j = None
        for n in nodo.preorden():
            k = self.indice_tok.get((n.linea, n.columna))
            if k is None:
                continue
            i = k if i is None or k < i else i
            j = k if j is None or k > j else j
        if i is None:
            return None
        bal = sum(self._balance(self.toks[k]) for k in range(i, j + 1))
        while bal > 0 and j + 1 < len(self.toks):     # cerrar lo que quedó abierto: f(x
            j += 1
            bal += self._balance(self.toks[j])
        return i, j

    def pos(self, x, largo=None, exacto=False):
        if isinstance(x, tuple):
            return x[0], x[1], largo or (x[2] if len(x) > 2 else 1)
        if exacto or largo:
            return x.linea, x.columna, largo or max(len(x.valor or ""), 1)
        r = self._indices(x)
        if r is None:
            return x.linea, x.columna, max(len(x.valor or ""), 1)
        a, b = self.toks[r[0]], self.toks[r[1]]
        return a.linea, a.columna, max(b.fin - a.inicio, 1)

    def texto(self, nodo, maximo=40):
        if nodo is None:
            return "?"
        r = self._indices(nodo)
        if r is None:
            return nodo.valor or nodo.tipo
        partes = []
        for k in range(r[0], r[1] + 1):
            t = self.toks[k]
            if partes and t.inicio > self.toks[k - 1].fin:
                partes.append(" ")
            partes.append(t.lexema)
        s = "".join(partes)
        return s if len(s) <= maximo else s[:maximo - 1] + "…"

    def pos_lexema(self, n, lexema):
        i = self.indice_tok.get((n.linea, n.columna))
        if i is not None and lexema:
            for k in range(i, min(i + 80, len(self.toks))):
                if self.toks[k].lexema == lexema:
                    t = self.toks[k]
                    return t.linea, t.columna, len(lexema)
        return n.linea, n.columna, max(len(lexema or ""), 1)

    def pos_nombre(self, n):
        corto = (n.valor or "").split("::")[-1].lstrip("~")
        if corto.startswith("operator"):
            corto = "operator"
        return self.pos_lexema(n, corto)

    def pos_linea(self, n):
        i = self.indice_tok.get((n.linea, n.columna))
        if i is None:
            return n.linea, n.columna, 1
        j = i
        while j + 1 < len(self.toks) and self.toks[j + 1].linea == self.toks[i].linea:
            j += 1
        return n.linea, n.columna, max(self.toks[j].fin - self.toks[i].inicio, 1)

    def cierre(self, bloque):
        """Posición de la '}' que cierra un bloque."""
        if bloque is None:
            return None
        i = self.indice_tok.get((bloque.linea, bloque.columna))
        if i is None or self.toks[i].lexema != "{":
            return bloque.linea, bloque.columna, 1
        bal = 0
        for k in range(i, len(self.toks)):
            bal += self._balance(self.toks[k], solo_llaves=True)
            if bal == 0:
                return self.toks[k].linea, self.toks[k].columna, 1
        return bloque.linea, bloque.columna, 1

    # ─────────────────────── pasos y errores ───────────────────────
    def ruta(self):
        return [a.corto for a in self.pila]

    def paso(self, regla, x, esperado="—", encontrado="—", mensaje="", largo=None, exacto=False,
             simbolo=None):
        l, c, lg = self.pos(x, largo, exacto)
        p = {"regla": regla, "linea": l, "columna": c, "largo": lg, "esperado": esperado,
             "encontrado": encontrado, "pila": self.ruta(), "error": False, "mensaje": mensaje}
        if simbolo is not None:
            p["simbolo"] = simbolo
        self.pasos.append(p)

    def error(self, x, mensaje, sugerencia="", regla="Verificación semántica", esperado="—",
              encontrado="—", largo=None, exacto=False):
        if len(self.errores) >= self.MAX_ERRORES:
            return
        l, c, lg = self.pos(x, largo, exacto)
        if any(e["linea"] == l and e["columna"] == c and e["mensaje"] == mensaje for e in self.errores):
            return
        self.errores.append({"fase": "Semántico", "mensaje": mensaje, "linea": l, "columna": c,
                             "sugerencia": sugerencia, "esperado": esperado,
                             "encontrado": encontrado, "regla": regla})
        self.pasos.append({"regla": regla, "linea": l, "columna": c, "largo": lg,
                           "esperado": esperado, "encontrado": encontrado, "pila": self.ruta(),
                           "error": True, "mensaje": mensaje})

    # ─────────────────────── ámbitos ───────────────────────
    def abrir(self, corto, tipo, x, ruta=None, tabla=None, clase=None, paso=True):
        padre = self.pila[-1]
        if ruta is None:
            ruta = corto if padre.tipo in ("global", "clase", "espacio") else f"{padre.nombre} › {corto}"
        amb = Ambito(ruta, corto, tipo, tabla if tabla is not None else {}, clase)
        self.pila.append(amb)
        if paso and x is not None:
            self.paso("Ámbito", x, "—", f"abre «{ruta}»",
                      f"Se abre el ámbito «{ruta}»: lo que se declare aquí solo existe dentro de él.",
                      exacto=not isinstance(x, tuple))
        return amb

    def cerrar(self, x=None, paso=True):
        amb = self.pila[-1]
        if paso and x is not None:
            n = sum(len(v) for v in amb.tabla.values()) if amb.tipo != "clase" else 0
            msg = (f"Se cierra «{amb.nombre}»: sus {plural(n, 'símbolo')} local{'es' if n != 1 else ''} "
                   f"dejan de estar visibles." if n else f"Se cierra «{amb.nombre}».")
            self.paso("Ámbito", x, "—", f"cierra «{amb.nombre}»", msg)
        self.pila.pop()

    # ─────────────────────── registro de símbolos ───────────────────────
    def describir(self, s):
        if s.categoria in ("función", "método", "constructor", "destructor"):
            ps = ", ".join(str(p.tipo) for p in (s.params or []))
            if s.variadico:
                ps += ", ..." if ps else "..."
            pre = "" if s.categoria in ("constructor", "destructor") else f"{s.tipo} "
            return f"{pre}({ps})" + (" const" if s.metodo_const else "")
        return s.extra or str(s.tipo)

    def firma(self, f):
        ps = ", ".join(str(p.tipo) for p in (f.params or []))
        if f.variadico:
            ps += ", ..." if ps else "..."
        return f"({ps})" + (" const" if f.metodo_const else "")

    def publicar(self, s, x, ambito, regla, mensaje=None):
        s.ambito = ambito
        idx = len(self.tabla)
        self.tabla.append(s)
        desc = self.describir(s)
        self.paso(regla, x, f"'{s.nombre}' nuevo en «{ambito}»", f"{s.categoria}: {desc}",
                  mensaje or f"Se agrega '{s.nombre}' a la tabla de símbolos ({s.categoria}, {desc}) "
                             f"en el ámbito {ambito}.", simbolo=idx, exacto=not isinstance(x, tuple))
        return s

    def registrar(self, s, x, amb=None, regla="Declaración", mensaje=None):
        amb = amb or self.pila[-1]
        amb.tabla.setdefault(s.nombre, []).append(s)
        return self.publicar(s, x, amb.nombre, regla, mensaje)

    def ya_declarado(self, nombre, amb, x):
        prev = amb.tabla.get(nombre)
        if prev:
            p = prev[0]
            self.error(x, f"'{nombre}' ya fue declarado en este ámbito (línea {p.linea}, como {p.categoria})",
                       "Usa otro nombre o elimina la declaración repetida.", "Redeclaración",
                       "nombre nuevo", f"'{nombre}' ya existe")
            return True
        return False

    def fila(self, s):
        return {"nombre": s.nombre, "categoria": s.categoria, "tipo": self.describir(s),
                "ambito": s.ambito, "linea": s.linea}

    # ─────────────────────── búsqueda de nombres ───────────────────────
    def miembro(self, info, nombre, vistos=None):
        if info is None:
            return []
        if nombre in info.miembros:
            return info.miembros[nombre]
        vistos = vistos or set()
        vistos.add(info.nombre)
        for b in info.bases:
            bi = self.clases.get(b)
            if bi is not None and bi.nombre not in vistos:
                r = self.miembro(bi, nombre, vistos)
                if r:
                    return r
        return []

    def buscar(self, nombre):
        """Lista de símbolos visibles con ese nombre (varios si es una función sobrecargada)."""
        if "::" in nombre:
            return self.buscar_calificado(nombre)
        for amb in reversed(self.pila):
            if amb is self.global_:
                for pl in reversed(self.plantillas):
                    if nombre in pl:
                        return [pl[nombre]]
            if amb.tipo == "clase" and amb.clase is not None:
                r = self.miembro(amb.clase, nombre)
                if r:
                    return r
            elif nombre in amb.tabla:
                return amb.tabla[nombre]
        for ns in self.espacios_usados:
            a = self.espacios.get(ns)
            if a is not None and nombre in a.tabla:
                return a.tabla[nombre]
        return []

    def buscar_calificado(self, nombre):
        pre, _, ult = nombre.rpartition("::")
        if pre == "":
            return self.global_.tabla.get(ult, [])
        if pre == "std":
            s = self.biblioteca(ult, None, forzado=True)
            return [s] if s else [Simbolo(ult, "biblioteca", DESCONOCIDO)]
        if pre in self.enumeradores and ult in self.enumeradores[pre]:
            return [self.enumeradores[pre][ult]]
        if pre in self.clases:
            return self.miembro(self.clases[pre], ult)
        if pre in self.espacios:
            return self.espacios[pre].tabla.get(ult, [])
        return [Simbolo(nombre, "biblioteca", DESCONOCIDO)]      # algo que no se puede revisar

    def nombres_visibles(self, solo_tipos=False):
        nombres = set()
        for amb in self.pila:
            fuente = amb.tabla
            if amb.tipo == "clase" and amb.clase is not None:
                fuente = dict(amb.tabla)
                for b in amb.clase.bases:
                    if b in self.clases:
                        fuente.update(self.clases[b].miembros)
            for k, v in fuente.items():
                if not solo_tipos or any(s.es_tipo for s in v):
                    nombres.add(k)
        for pl in self.plantillas:
            nombres.update(pl)
        if solo_tipos:
            nombres.update(TIPOS_BIBLIOTECA | BASICOS)
        elif self.std:
            nombres.update(OBJETOS_BIBLIOTECA)
        return nombres

    def parecido(self, nombre, solo_tipos=False, opciones=None):
        cands = [n for n in (opciones if opciones is not None else self.nombres_visibles(solo_tipos))
                 if n != nombre]
        r = difflib.get_close_matches(nombre, cands, n=1, cutoff=0.75)
        return r[0] if r else None

    def biblioteca(self, nombre, x, forzado=False):
        if nombre in FUNCIONES_BIBLIOTECA:
            ret, mn, mx, con_std, clase = FUNCIONES_BIBLIOTECA[nombre]
            s = Simbolo(nombre, "biblioteca", texto_a_tipo(ret) if ret != "?" else DESCONOCIDO,
                        lib=(mn, mx, clase))
        elif nombre in OBJETOS_BIBLIOTECA:
            ret, con_std = OBJETOS_BIBLIOTECA[nombre]
            s = Simbolo(nombre, "biblioteca", texto_a_tipo(ret) if ret != "?" else DESCONOCIDO)
        elif nombre in TIPOS_BIBLIOTECA:
            con_std = nombre not in SIN_STD
            s = Simbolo(nombre, "tipo de biblioteca", Tipo(nombre), es_tipo=True)
        else:
            return None
        if x is not None:
            if con_std and not forzado:
                self.requiere_std(nombre, x)
            self.requiere_cabecera(nombre, x)
        return s

    def requiere_std(self, nombre, x):
        if self.std or nombre in self.std_nombres or ("std", nombre) in self.reportados:
            return
        self.reportados.add(("std", nombre))
        self.error(x, f"'{nombre}' pertenece al espacio de nombres std y aquí no está visible",
                   f"Escribe std::{nombre} o agrega 'using namespace std;' después de los #include.",
                   "Espacio de nombres", f"std::{nombre}", nombre)

    def requiere_cabecera(self, nombre, x):
        req = CABECERAS.get(nombre)
        if (not req or "bits/stdc++.h" in self.cabeceras or self.cabeceras & set(req)
                or ("cab", nombre) in self.reportados):
            return
        self.reportados.add(("cab", nombre))
        self.error(x, f"Se usa '{nombre}' pero falta #include <{req[0]}>",
                   f"Agrega #include <{req[0]}> al inicio del archivo.", "Biblioteca",
                   f"#include <{req[0]}>", "no incluida")

    # ─────────────────────── tipos ───────────────────────
    def cat(self, t):
        if t is None:
            return "?"
        n = limpio(t.nombre)
        if n in ("?", "auto"):
            return "?"
        if n == "{}":
            return "lista"
        if n == "<función>":
            return "funcion"
        if t.dims:
            return "arreglo"
        if t.punteros:
            return "puntero"
        if n in ENTEROS:
            return "entero"
        if n in REALES:
            return "real"
        if n == "bool":
            return "bool"
        if n == "void":
            return "void"
        if n == "nullptr_t":
            return "nulo"
        b = base(n)
        if b in self.clases:
            return "clase"
        if b in self.enums:
            return "enum" if self.enums[b] else "enum_simple"
        if b in CADENAS:
            return "cadena"
        if b in FLUJOS:
            return "flujo"
        if b in CONTENEDORES:
            return "contenedor"
        if b in TIPOS_BIBLIOTECA:
            return "std"
        return "?"

    def info_clase(self, t):
        return self.clases.get(base(t.nombre)) if t is not None else None

    def combinar(self, sim, t):
        if sim.categoria == "parámetro de plantilla":
            return DESCONOCIDO
        if sim.categoria != "alias":
            return t
        a = sim.tipo
        if a.nombre == "?":
            return DESCONOCIDO
        if t.punteros:
            cb = (a.const if not a.punteros else a.const_base) or t.const_base
            return Tipo(a.nombre, a.punteros + t.punteros, t.ref or a.ref, t.const, cb, t.dims + a.dims)
        return Tipo(a.nombre, a.punteros, t.ref or a.ref, a.const or t.const, a.const_base, t.dims + a.dims)

    def resolver(self, t, nodo=None, reportar=True):
        """Sustituye alias y parámetros de plantilla, y revisa que el tipo exista."""
        crudo = t.nombre
        n = limpio(crudo)
        forzado = crudo.startswith("std::")
        t = replace(t, nombre=n)
        if n in BASICOS or n in ("?", "{}", "<función>"):
            return t
        avisar = reportar and nodo is not None
        if "::" in n:
            pre, _, ult = n.rpartition("::")
            fuente = (self.espacios[pre].tabla if pre in self.espacios
                      else self.clases[pre].miembros if pre in self.clases else {})
            sims = [s for s in fuente.get(ult, []) if s.es_tipo]
            if sims:
                return self.combinar(sims[0], replace(t, nombre=ult))
            return DESCONOCIDO
        b = base(n)
        sims = [s for s in self.buscar(b) if s.es_tipo]
        if sims:
            if avisar:
                for a in args_plantilla(crudo):
                    self.resolver(texto_a_tipo(a), nodo)
            return self.combinar(sims[0], t)
        if b in TIPOS_BIBLIOTECA:
            if avisar:
                if b not in SIN_STD and not forzado:
                    self.requiere_std(b, nodo)
                self.requiere_cabecera(b, nodo)
                for a in args_plantilla(crudo):
                    self.resolver(texto_a_tipo(a), nodo)
            return t
        if not avisar or self.cabeceras_locales:
            return DESCONOCIDO
        otros = self.buscar(b)
        if otros:
            s = otros[0]
            self.error(nodo, f"'{b}' no es un tipo de dato; es {art(s.categoria)} (línea {s.linea})",
                       "Escribe un tipo válido (int, double, string, una clase...) antes del nombre.",
                       "Tipo de dato", "tipo", f"{s.categoria} '{b}'")
        else:
            p = self.parecido(b, solo_tipos=True)
            self.error(nodo, f"El tipo '{b}' no está declarado",
                       (f"¿Quisiste decir '{p}'? " if p else "")
                       + f"Declara la clase o struct '{b}' antes de usarla, o revisa que el nombre esté bien escrito.",
                       "Tipo de dato", "tipo declarado", f"'{b}' desconocido")
        return DESCONOCIDO

    def tipo_de(self, nodo_tipo):
        return self.resolver(texto_a_tipo(nodo_tipo.valor), nodo_tipo) if nodo_tipo is not None else DESCONOCIDO

    def elemento_contenedor(self, t, i=0):
        args = args_plantilla(t.nombre)
        if len(args) <= i:
            return DESCONOCIDO
        return self.resolver(texto_a_tipo(args[i]), None, reportar=False)

    def hereda(self, der, b):
        der, b = base(der), base(b)
        vistos, cola = set(), [der]
        while cola:
            x = cola.pop()
            if x == b:
                return True
            if x in vistos:
                continue
            vistos.add(x)
            info = self.clases.get(x)
            if info is not None:
                cola.extend(info.bases)
        return False

    def mismo_contenedor(self, a, b):
        if base(a.nombre) != base(b.nombre):
            return False
        for x, y in zip(args_plantilla(a.nombre), args_plantilla(b.nombre)):
            tx = self.resolver(texto_a_tipo(x), None, False)
            ty = self.resolver(texto_a_tipo(y), None, False)
            if "?" in (tx.nombre, ty.nombre):
                continue
            if str(sin_cv(tx)) != str(sin_cv(ty)):
                return False
        return True

    def a_bool(self, t):
        c = self.cat(t)
        if c in NUMERICAS | PUNTEROS | LIBRES | {"nulo", "flujo", "lista"}:
            return True
        if c == "clase":
            return bool(self.miembro(self.info_clase(t), "operator bool"))
        return False

    def promover(self, a, b):
        ts = [sin_cv(a), sin_cv(b)]
        reales = [t.nombre for t in ts if self.cat(t) == "real"]
        if reales:
            if "long double" in reales:
                return Tipo("long double")
            if "double" in reales:
                return DOUBLE
            return FLOAT
        nombres = {t.nombre for t in ts}
        for n in ("unsigned long long", "long long", "unsigned long", "long", "size_t", "unsigned int"):
            if n in nombres:
                return Tipo(n)
        return INT

    def es_cero_literal(self, n):
        return n is not None and ((n.tipo == "LiteralEntero" and entero_literal(n.valor) == 0)
                                  or (n.tipo == "LiteralNulo" and n.valor == "NULL"))

    def compatible(self, dest, orig, nodo=None, contexto="init", prof=0):
        """¿Se puede guardar un valor de tipo 'orig' en algo de tipo 'dest'?"""
        if orig is None or orig.nombre == "{}":
            return True
        d = replace(dest, ref=False)
        cd, co = self.cat(d), self.cat(orig)
        if cd in LIBRES or co in LIBRES:
            return True
        if co in ("void", "funcion") or cd == "void":
            return False
        if cd == "puntero":
            if co == "nulo" or self.es_cero_literal(nodo):
                return True
            if co not in PUNTEROS:
                return False
            o = decaer(orig)
            if d.nombre == "void" and d.punteros == 1:
                return not o.const_base or d.const_base
            if o.punteros != d.punteros:
                return False
            if o.const_base and not d.const_base and not (nodo is not None and nodo.tipo == "LiteralCadena"):
                return False
            if o.nombre == d.nombre or "?" in (o.nombre, d.nombre):
                return True
            return self.cat(Tipo(o.nombre)) == "clase" and self.hereda(o.nombre, d.nombre)
        if cd == "arreglo":
            return (contexto == "init" and d.nombre in ("char", "wchar_t") and len(d.dims) == 1
                    and nodo is not None and nodo.tipo == "LiteralCadena")
        if cd == "cadena":
            return (co == "cadena" or es_texto_c(orig)
                    or (contexto == "asig" and es_char(orig)))
        if cd in ("entero", "real", "bool"):
            if co in NUMERICAS:
                return True
            return cd == "bool" and co in PUNTEROS | {"nulo"}
        if cd in ("enum", "enum_simple"):
            return co == cd and base(orig.nombre) == base(d.nombre)
        if cd == "contenedor":
            return co == "contenedor" and self.mismo_contenedor(d, orig)
        if cd == "clase":
            if co == "clase" and self.hereda(orig.nombre, d.nombre):
                return True
            info = self.info_clase(d)
            if info is None or prof > 2:
                return info is None
            for c in info.constructores:            # constructor de conversión
                if c.explicito or c.borrado or not c.params or not self.acepta_cantidad(c, 1):
                    continue
                if self.compatible(sin_cv(c.params[0].tipo), orig, nodo, "param", prof + 1):
                    return True
            return False
        if cd == "flujo":
            return co == "flujo"
        if cd == "nulo":
            return co == "nulo"
        return False

    def sugerencia_tipos(self, dest, t, nodo=None):
        cd, co = self.cat(dest), self.cat(t)
        if co == "void":
            return "La expresión no devuelve ningún valor (la función es void), así que su resultado no se puede guardar ni usar."
        if co == "funcion":
            return f"Faltan los paréntesis para llamar a la función: {self.texto(nodo)}(...)."
        if cd == "cadena" and co in NUMERICAS:
            if es_char(t):
                return 'Para texto usa comillas dobles ("a"); para convertir un número usa to_string(valor).'
            return "Para guardar un número como texto conviértelo con to_string(valor)."
        if cd in NUMERICAS and (co == "cadena" or es_texto_c(t)):
            if nodo is not None and nodo.tipo == "LiteralCadena":
                if dest.nombre == "char":
                    return "Para un solo carácter usa comillas simples: 'a'."
                if re.fullmatch(r'"\s*-?\d+(\.\d+)?\s*"', nodo.valor or ""):
                    return "Quita las comillas si querías el número; entre comillas es texto."
            return "Para convertir texto a número usa stoi() (enteros) o stod() (decimales)."
        if cd == "puntero" and co not in PUNTEROS:
            return (f"Un puntero guarda direcciones de memoria: usa '&' para obtener la dirección de una "
                    f"variable (por ejemplo: {dest} p = &variable;) o nullptr.")
        if cd not in PUNTEROS and co in PUNTEROS:
            return "Para obtener el valor al que apunta el puntero usa '*': *puntero."
        if cd in ("enum", "enum_simple"):
            return f"Usa uno de los valores de la enumeración {dest.nombre}, o conviértelo con static_cast<{dest.nombre}>(...)."
        if cd == "clase" or co == "clase":
            return f"{dest} y {t} no son compatibles; crea un objeto del tipo correcto o revisa el tipo de la variable."
        if cd == "contenedor":
            return f"Los dos deben ser exactamente del mismo tipo ({dest})."
        return f"Usa un valor de tipo {dest} o cambia el tipo de la variable."

    def compatible_o_error(self, dest, t, nodo, contexto, nombre, regla):
        if self.compatible(dest, t, nodo, contexto):
            if self.cat(t) in LIBRES:
                self.paso("Compatibilidad de tipos", nodo, str(dest), "no determinado",
                          "El tipo del valor no se puede determinar aquí (viene de la biblioteca o de un "
                          "error anterior), así que se acepta sin marcar otro error.")
                return True
            if contexto == "return":
                msg = f"El valor devuelto ({t}) es compatible con el tipo de retorno de '{nombre}' ({dest})."
            else:
                msg = f"El valor ({t}) es compatible con '{nombre}' ({dest})."
            self.paso("Compatibilidad de tipos", nodo, str(dest), str(t), msg)
            return True
        if contexto == "init":
            msg = f"No se puede inicializar '{nombre}' ({dest}) con un valor de tipo {t}"
        elif contexto == "asig":
            msg = f"No se puede asignar un valor de tipo {t} a '{nombre}' ({dest})"
        elif contexto == "return":
            msg = f"'{nombre}' debe devolver {dest}, pero aquí se devuelve {t}"
        else:
            msg = f"Se esperaba {dest} y se encontró {t}"
        sug = self.sugerencia_tipos(dest, t, nodo)
        if contexto == "return" and nombre == "main":
            sug = "main le devuelve un número entero al sistema operativo: escribe return 0; cuando el programa termina bien."
        self.error(nodo, msg, sug, regla, str(dest), str(t))
        return False

    def valor_constante(self, n, prof=0):
        """Valor numérico de una expresión constante, o None."""
        if n is None or prof > 25:
            return None
        t = n.tipo
        if t == "LiteralEntero":
            return entero_literal(n.valor)
        if t == "LiteralFlotante":
            return real_literal(n.valor)
        if t == "LiteralCarácter":
            return caracter_literal(n.valor)
        if t == "LiteralBooleano":
            return 1 if n.valor == "true" else 0
        if t == "LiteralNulo" and n.valor == "NULL":
            return 0
        if t == "Unaria" and n.valor in ("-", "+") and n.hijos:
            v = self.valor_constante(n.hijos[0], prof + 1)
            return None if v is None else (-v if n.valor == "-" else v)
        if t == "Binaria" and n.valor in ("+", "-", "*", "/", "%") and len(n.hijos) == 2:
            a = self.valor_constante(n.hijos[0], prof + 1)
            b = self.valor_constante(n.hijos[1], prof + 1)
            if a is None or b is None:
                return None
            if n.valor == "+":
                return a + b
            if n.valor == "-":
                return a - b
            if n.valor == "*":
                return a * b
            if b == 0:
                return None
            if n.valor == "/":
                return int(a / b) if isinstance(a, int) and isinstance(b, int) else a / b
            if isinstance(a, int) and isinstance(b, int):
                return int(math.fmod(a, b))
            return None
        if t == "Conversión" and n.hijos:
            v = self.valor_constante(n.hijos[-1], prof + 1)
            destino = n.hijos[0].valor if n.valor in CASTS and n.hijos[0].tipo == "Tipo" else n.valor
            if v is not None and self.cat(texto_a_tipo(destino)) == "entero":
                return int(v)
            return v
        if t == "Identificador":
            sims = self.buscar(n.valor)
            if sims and sims[0].valor is not None and sims[0].categoria in (
                    "macro", "enumerador", "variable", "atributo"):
                return sims[0].valor
        return None

    def es_constante_expr(self, n):
        for x in n.preorden():
            if x.tipo in ("Llamada", "Asignación", "Postfijo"):
                return False
            if x.tipo == "Identificador":
                sims = self.buscar(x.valor)
                if sims and sims[0].categoria in ("variable", "parámetro", "atributo") and not sims[0].tipo.const:
                    return False
        return True

    # ═══════════════════════════ recorrido principal ═══════════════════════════
    def ejecutar(self):
        self.paso("Inicio del análisis", (1, 1, 1), "árbol sintáctico", "Programa",
                  "Se recorre el árbol sintáctico de arriba hacia abajo para llenar la tabla de "
                  "símbolos y revisar los tipos de cada declaración, expresión y llamada.")
        for h in self.arbol.hijos:
            self.seguro(self.declaracion, h)
        ult = self.toks[-1] if self.toks else None
        self.paso("Fin del análisis", (ult.linea, ult.columna, len(ult.lexema)) if ult else (1, 1, 1),
                  "—", f"{len(self.tabla)} símbolos",
                  f"Análisis semántico terminado: {plural(len(self.tabla), 'símbolo')} en la tabla y "
                  f"{len(self.errores)} error(es).")
        return {"simbolos": [self.fila(s) for s in self.tabla], "errores": self.errores,
                "pasos": self.pasos}

    def seguro(self, fn, *args):
        """Ejecuta una parte del análisis; si algo inesperado falla, sigue con lo demás."""
        estado = (len(self.pila), self.ctx, self.ciclos, self.switches, len(self.plantillas))
        try:
            return fn(*args)
        except Exception as ex:          # noqa: BLE001 — el análisis no debe detenerse
            if DEPURAR:
                raise
            del self.pila[estado[0]:]
            self.ctx, self.ciclos, self.switches = estado[1], estado[2], estado[3]
            del self.plantillas[estado[4]:]
            x = args[0] if args and hasattr(args[0], "linea") else (1, 1, 1)
            self.paso("Aviso", x, "—", "—", f"Esta parte no se pudo analizar ({type(ex).__name__}); "
                                            f"se continúa con el resto del programa.", exacto=True)
            return None

    def declaracion(self, n):
        t = n.tipo
        if t == "Directiva":
            self.directiva(n)
        elif t == "UsingNamespace":
            self.using_namespace(n)
        elif t == "DirectivaUsing":
            self.using(n)
        elif t == "EspacioNombres":
            self.espacio(n)
        elif t == "Plantilla":
            self.plantilla(n)
        elif t == "Typedef":
            self.typedef(n)
        elif t == "Enumeración":
            self.enumeracion(n)
        elif t in ("Clase", "Estructura", "Unión"):
            self.clase(n)
        elif t in ("Función", "Prototipo", "Constructor", "Destructor"):
            self.funcion(n)
        elif t == "DeclaraciónGlobal":
            self.declarar_variables(n, "variable")

    # ─────────────────────── directivas y using ───────────────────────
    def tipo_texto(self, valor):
        v = re.sub(r"^([+-])\s+", r"\1", (valor or "").strip())
        if re.fullmatch(r"[+-]?(0[xX][0-9a-fA-F']+|0[bB][01']+|\d[\d']*)[uUlL]*", v):
            n = entero_literal(v.lstrip("+-"))
            return INT, (-n if v.startswith("-") and n is not None else n)
        if re.fullmatch(r"[+-]?(\d[\d']*\.\d*|\.\d+|\d+)([eE][+-]?\d+)?[fFlL]?", v):
            return (FLOAT if v[-1] in "fF" else DOUBLE), real_literal(v)
        if v.startswith('"'):
            return CSTR, None
        if re.fullmatch(r"'(\\.|[^'])'", v):
            return CHAR, caracter_literal(v)
        if v in ("true", "false"):
            return BOOL, int(v == "true")
        return DESCONOCIDO, None

    def directiva(self, n):
        partes = (n.valor or "").split(None, 1)
        if not partes:
            return
        nombre, resto = partes[0], (partes[1] if len(partes) > 1 else "")
        if nombre == "include":
            if resto.startswith("<"):
                self.cabeceras.add(resto.strip("<> "))
                self.paso("Directiva #include", self.pos_linea(n), "biblioteca", resto,
                          f"Se incluye la biblioteca {resto}; sus funciones y tipos quedan disponibles.")
            else:
                self.cabeceras_locales = True
                self.paso("Directiva #include", self.pos_linea(n), "archivo propio", resto,
                          f"Se incluye {resto}. Como ese archivo no se analiza aquí, no se marcarán como "
                          f"error las funciones o tipos que no se encuentren.")
        elif nombre == "define":
            p = resto.split(None, 1)
            if not p or self.global_.tabla.get(p[0]):
                return
            macro, valor = p[0], (p[1] if len(p) > 1 else "")
            t, v = self.tipo_texto(valor)
            s = Simbolo(macro, "macro", t, n.linea, n.columna, valor=v,
                        extra=f"{t} = {valor}" if valor and t.nombre != "?" else (valor or "sin valor"))
            self.registrar(s, self.pos_lexema(n, macro), self.global_, "Directiva #define",
                           f"Se registra la constante '{macro}'" + (f" = {valor} ({t})" if valor else "")
                           + "; el preprocesador la sustituye en todo el programa.")

    def using_namespace(self, n):
        ns = n.valor
        if ns == "std" or ns.startswith("std::"):
            self.std = True
            self.paso("Directiva using", self.pos_linea(n), "espacio de nombres", ns,
                      "Desde aquí los nombres de std (cout, cin, string, vector...) se pueden usar sin std::.")
        elif ns in self.espacios:
            self.espacios_usados.add(ns)
            self.paso("Directiva using", self.pos_linea(n), "espacio de nombres", ns,
                      f"Los nombres del espacio '{ns}' se pueden usar sin {ns}::.")
        else:
            self.error(self.pos_linea(n), f"El espacio de nombres '{ns}' no está declarado",
                       "Revisa el nombre o declara el namespace antes de usarlo.", "Directiva using",
                       "namespace declarado", ns)

    def using(self, n):
        tn = self.hijo(n, "Tipo")
        if tn is not None:                       # using Alias = tipo;
            self.declarar_alias(n.valor, self.tipo_de(tn), n)
            return
        pre, _, ult = (n.valor or "").rpartition("::")
        if pre == "std":
            self.std_nombres.add(ult)
            self.paso("Directiva using", self.pos_linea(n), "nombre de std", n.valor,
                      f"'{ult}' se puede usar sin escribir std::.")
        elif pre in self.espacios and ult in self.espacios[pre].tabla:
            self.pila[-1].tabla[ult] = self.espacios[pre].tabla[ult]
        elif pre and pre not in self.clases:
            self.error(self.pos_linea(n), f"'{n.valor}' no está declarado", "Revisa el nombre completo.",
                       "Directiva using", "nombre declarado", n.valor)

    def espacio(self, n):
        nombre = n.valor or "(anónimo)"
        amb = self.espacios.get(nombre)
        if amb is None:
            amb = Ambito(nombre, nombre, "espacio")
            self.espacios[nombre] = amb
            s = Simbolo(nombre, "espacio de nombres", DESCONOCIDO, n.linea, n.columna, extra="namespace")
            self.publicar(s, self.pos_lexema(n, n.valor) if n.valor else n, self.pila[-1].nombre,
                          "Espacio de nombres")
        if not n.valor:
            self.espacios_usados.add(nombre)
        self.pila.append(amb)
        try:
            for h in n.hijos:
                self.seguro(self.declaracion, h)
        finally:
            self.pila.pop()

    def plantilla(self, n, info=None, acceso="public"):
        params = {}
        hijo = n.hijos[0] if n.hijos else None
        donde = f"plantilla {hijo.valor}" if hijo is not None and hijo.valor else "plantilla"
        for p in (n.valor or "").split(","):
            pal = p.split()
            if not pal:
                continue
            es_tipo = len(pal) == 1
            t = DESCONOCIDO if es_tipo else self.resolver(texto_a_tipo(" ".join(pal[:-1])), None, False)
            s = Simbolo(pal[-1], "parámetro de plantilla", t, n.linea, n.columna, es_tipo=es_tipo,
                        extra="typename" if es_tipo else str(t))
            params[pal[-1]] = s
            self.publicar(s, self.pos_lexema(n, pal[-1]), donde, "Parámetro de plantilla",
                          f"'{pal[-1]}' es un parámetro de la plantilla: representa "
                          f"{'cualquier tipo' if es_tipo else 'un valor constante'} que se elige al usarla.")
        self.plantillas.append(params)
        try:
            for h in n.hijos:
                if h.tipo in ("Clase", "Estructura", "Unión"):
                    self.clase(h, plantilla=True)
                elif info is not None and h.tipo in ("Método", "Prototipo", "Constructor", "Destructor"):
                    s = self.miembro_funcion(h, info, acceso)
                    if s is not None and self.hijo(h, "Bloque") is not None:
                        self.cuerpo_miembro(h, s, info)
                else:
                    self.declaracion(h)
        finally:
            self.plantillas.pop()

    def typedef(self, n):
        self.declarar_alias(n.valor, self.tipo_de(self.hijo(n, "Tipo")), n)

    def declarar_alias(self, nombre, t, n):
        amb = self.pila[-1]
        x = self.pos_lexema(n, nombre)
        if self.ya_declarado(nombre, amb, x):
            return
        s = Simbolo(nombre, "alias", t, n.linea, n.columna, es_tipo=True, extra=f"= {t}")
        self.registrar(s, x, amb, "Alias de tipo", f"'{nombre}' se registra como otro nombre para el tipo {t}.")

    def enumeracion(self, n):
        nombre = n.valor
        i = self.indice_tok.get((n.linea, n.columna))
        con_ambito = i is not None and i + 1 < len(self.toks) and self.toks[i + 1].lexema in ("class", "struct")
        amb = self.pila[-1]
        x = self.pos_lexema(n, nombre)
        if self.ya_declarado(nombre, amb, x):
            return
        self.enums[nombre] = con_ambito
        s = Simbolo(nombre, "enumeración", Tipo(nombre), n.linea, n.columna, es_tipo=True,
                    extra="enum class" if con_ambito else "enum")
        self.registrar(s, x, amb, "Declaración de enumeración",
                       f"Se registra la enumeración '{nombre}' como un nuevo tipo de dato.")
        valores = self.enumeradores.setdefault(nombre, {})
        siguiente = 0
        for e in self.hijos(n, "Enumerador"):
            if e.hijos:
                te = self.expr(e.hijos[0])
                if self.cat(te) not in ENTERAS | LIBRES:
                    self.error(e.hijos[0], f"El valor de '{e.valor}' debe ser un número entero; se encontró {te}",
                               "Los valores de una enumeración son enteros: enum Color { ROJO = 1, VERDE = 2 };",
                               "Enumeración", "entero", str(te))
                v = self.valor_constante(e.hijos[0])
            else:
                v = siguiente
            siguiente = v + 1 if isinstance(v, int) else None
            pe = (e.linea, e.columna, len(e.valor))
            if e.valor in valores or (not con_ambito and self.ya_declarado(e.valor, amb, pe)):
                if e.valor in valores:
                    self.error(pe, f"'{e.valor}' aparece dos veces en la enumeración '{nombre}'",
                               "Cada valor de la enumeración debe tener un nombre distinto.",
                               "Enumeración", "nombre nuevo", e.valor)
                continue
            se = Simbolo(e.valor, "enumerador", Tipo(nombre), e.linea, e.columna, valor=v,
                         extra=f"{nombre} = {v}" if v is not None else nombre)
            valores[e.valor] = se
            if con_ambito:
                self.publicar(se, pe, nombre, "Valor de enumeración")
            else:
                self.registrar(se, pe, amb, "Valor de enumeración")

    # ─────────────────────── clases ───────────────────────
    def clase(self, n, plantilla=False):
        nombre = n.valor
        clave = {"Clase": "class", "Estructura": "struct", "Unión": "union"}[n.tipo]
        categoria = {"class": "clase", "struct": "struct", "union": "unión"}[clave]
        x = self.pos_lexema(n, nombre)
        i = self.indice_tok.get((n.linea, n.columna))
        adelantada = (not n.hijos and i is not None and i + 2 < len(self.toks)
                      and self.toks[i + 2].lexema == ";")
        amb = self.pila[-1]
        info = self.clases.get(nombre)
        if info is None:
            if self.ya_declarado(nombre, amb, x):
                return
            info = InfoClase(nombre, clave, n.linea, plantilla=plantilla)
            self.clases[nombre] = info
            s = Simbolo(nombre, categoria, Tipo(nombre), n.linea, n.columna, es_tipo=True,
                        extra=("plantilla " if plantilla else "") + clave)
            self.registrar(s, x, amb, "Declaración de clase",
                           f"Se registra {art(categoria)} '{nombre}' como un nuevo tipo de dato.")
        elif info.completa and not adelantada:
            self.error(x, f"La {categoria} '{nombre}' ya fue definida en la línea {info.linea}",
                       "Cada clase se define una sola vez; usa otro nombre o elimina la definición repetida.",
                       "Declaración de clase", "nombre nuevo", f"'{nombre}' ya existe")
            return
        if adelantada:
            return
        info.linea, info.clave = n.linea, clave
        for h in self.hijos(n, "Hereda"):
            for tb in h.hijos:
                pal = [p for p in tb.valor.split() if p not in ("public", "private", "protected", "virtual")]
                b = base(" ".join(pal))
                if b in self.clases and self.clases[b].completa and b != nombre:
                    info.bases.append(b)
                    self.paso("Herencia", tb, "clase base declarada", b,
                              f"'{nombre}' hereda los atributos y métodos de '{b}'.")
                elif b in TIPOS_BIBLIOTECA or any(b in pl for pl in self.plantillas):
                    continue
                else:
                    falta = "solo está declarada (falta su definición)" if b in self.clases else "no está declarada"
                    self.error(tb, f"La clase base '{b}' {falta}",
                               "Define la clase base completa antes de la clase que hereda de ella.",
                               "Herencia", "clase definida", b)
        acceso = "private" if clave == "class" else "public"
        self.abrir(nombre, "clase", x, ruta=nombre, tabla=info.miembros, clase=info)
        pendientes, despues = [], []
        for h in n.hijos:
            t = h.tipo
            if t == "Acceso":
                acceso = h.valor
                self.paso("Especificador de acceso", h, "public / private / protected", h.valor,
                          f"Los miembros que siguen son {h.valor}.", exacto=True)
            elif t == "Campo":
                self.seguro(self.declarar_variables, h, "atributo", info, acceso)
            elif t in ("Método", "Prototipo", "Constructor", "Destructor"):
                s = self.seguro(self.miembro_funcion, h, info, acceso)
                if s is not None and self.hijo(h, "Bloque") is not None:
                    pendientes.append((h, s))
            elif t in ("Clase", "Estructura", "Unión"):
                self.seguro(self.clase, h)
            elif t == "Enumeración":
                self.seguro(self.enumeracion, h)
            elif t == "Typedef":
                self.seguro(self.typedef, h)
            elif t == "DirectivaUsing":
                self.seguro(self.using, h)
            elif t == "Plantilla":
                self.seguro(self.plantilla, h, info, acceso)
            elif t == "Variable":
                despues.append(h)
        info.completa = True
        for b in info.bases:                    # virtuales puros heredados sin implementar
            for nm in self.clases[b].puras:
                if not any(m.categoria == "método" and not m.virtual_pura for m in info.miembros.get(nm, [])):
                    info.puras.add(nm)
        # segunda pasada: valores iniciales de atributos y cuerpos de métodos
        for s, init in info.inits:
            self.seguro(self.init_atributo, s, init, info)
        for h, s in pendientes:
            self.seguro(self.cuerpo_miembro, h, s, info)
        self.cerrar(self.cierre_clase(n))
        for v in despues:
            self.seguro(self.declarar_variable, v, Tipo(nombre), set(), "variable")

    def cierre_clase(self, n):
        i = self.indice_tok.get((n.linea, n.columna))
        if i is None:
            return None
        for k in range(i, len(self.toks)):
            if self.toks[k].lexema == "{":
                fake = type("N", (), {"linea": self.toks[k].linea, "columna": self.toks[k].columna})
                return self.cierre(fake)
        return None

    def init_atributo(self, s, init, info):
        prev = self.ctx
        self.ctx = Contexto(None, info)
        try:
            if init.tipo == "ListaInicialización":
                self.revisar_lista(sin_cv(s.tipo), init, s.nombre)
            else:
                self.init_expresion(s.tipo, init, s.nombre)
        finally:
            self.ctx = prev

    def virtual_en_bases(self, info, nombre, vistos=None):
        vistos = vistos or set()
        for b in info.bases:
            bi = self.clases.get(b)
            if bi is None or b in vistos:
                continue
            vistos.add(b)
            if any(m.categoria == "método" and (m.virtual or m.virtual_pura) for m in bi.miembros.get(nombre, [])):
                return True
            if self.virtual_en_bases(bi, nombre, vistos):
                return True
        return False

    def miembro_funcion(self, h, info, acceso):
        mods = self.especificadores(h)
        params, variadico = self.leer_params(self.hijo(h, "Parámetros"))
        calif = {c.valor for c in self.hijos(h, "Calificador")}
        igual = self.hijo(h, "Igual")
        igual = igual.valor if igual is not None else ""
        cuerpo = self.hijo(h, "Bloque")
        tn = self.hijo(h, "Tipo")
        nombre = h.valor
        x = self.pos_nombre(h)
        if "friend" in mods:
            ret = self.tipo_de(tn) if tn is not None else VOID
            info.amigos.add(nombre)
            return self.declarar_funcion(nombre, ret, params, variadico, h, cuerpo is not None, self.global_)
        if h.tipo == "Constructor" or (tn is None and nombre == info.nombre):
            for c in info.constructores:
                if self.misma_firma(c.params, params):
                    self.error(x, f"Ya existe un constructor de '{info.nombre}' con los parámetros {self.firma(c)} (línea {c.linea})",
                               "Cambia los parámetros de uno de los constructores o elimina el repetido.",
                               "Constructor", "parámetros distintos", self.firma(c))
                    return None
            s = Simbolo(info.nombre, "constructor", Tipo(info.nombre), h.linea, h.columna, params=params,
                        variadico=variadico, definida=cuerpo is not None or igual == "default",
                        clase=info.nombre, acceso=acceso, explicito="explicit" in mods,
                        borrado=igual == "delete")
            info.constructores.append(s)
            self.publicar(s, x, info.nombre, "Constructor",
                          f"Se registra un constructor de '{info.nombre}' que recibe {self.firma(s)}.")
            return s
        if h.tipo == "Destructor" or nombre.startswith("~"):
            if info.destructor is not None:
                self.error(x, f"La clase '{info.nombre}' ya tiene un destructor (línea {info.destructor.linea})",
                           "Una clase solo puede tener un destructor.", "Destructor", "un destructor", "dos")
                return None
            s = Simbolo(nombre, "destructor", VOID, h.linea, h.columna, params=params,
                        definida=cuerpo is not None, clase=info.nombre, acceso=acceso,
                        virtual="virtual" in mods)
            info.destructor = s
            self.publicar(s, x, info.nombre, "Destructor")
            return s
        ret = self.tipo_de(tn) if tn is not None else VOID
        previos = info.miembros.get(nombre, [])
        if previos and previos[0].categoria != "método":
            self.error(x, f"'{nombre}' ya es {art(previos[0].categoria)} de la clase '{info.nombre}' (línea {previos[0].linea})",
                       "Usa nombres distintos para atributos y métodos.", "Declaración de método",
                       "nombre nuevo", f"'{nombre}' ya existe")
            return None
        es_const = "const" in calif
        for m in previos:
            if self.misma_firma(m.params, params) and m.metodo_const == es_const:
                self.error(x, f"El método '{nombre}{self.firma(m)}' ya fue declarado en la clase '{info.nombre}' (línea {m.linea})",
                           "Elimina la declaración repetida o cambia sus parámetros para sobrecargarlo.",
                           "Declaración de método", "método nuevo", "método repetido")
                return None
        s = Simbolo(nombre, "método", ret, h.linea, h.columna, params=params, variadico=variadico,
                    definida=cuerpo is not None, clase=info.nombre, acceso=acceso, metodo_const=es_const,
                    estatico="static" in mods, virtual="virtual" in mods or "override" in calif,
                    virtual_pura=igual == "0")
        if s.virtual_pura:
            info.puras.add(nombre)
        if "override" in calif and not self.virtual_en_bases(info, nombre):
            self.error(x, f"'{nombre}' está marcado override, pero ninguna clase base tiene un método virtual con ese nombre",
                       "Revisa el nombre del método o declara el de la clase base como virtual.",
                       "Declaración de método", "método virtual en la base", nombre)
        if not s.virtual and self.virtual_en_bases(info, nombre):
            s.virtual = True
        self.registrar(s, x, None, "Declaración de método",
                       f"Se registra el método {acceso} '{nombre}' de '{info.nombre}': {self.describir(s)}.")
        return s

    def cuerpo_miembro(self, h, s, info):
        cuerpo = self.hijo(h, "Bloque")
        if s.categoria == "función":            # función friend definida dentro de la clase
            guardada = self.pila.pop() if self.pila[-1].clase is info else None
            try:
                self.cuerpo_funcion(s, h, self.leer_params(self.hijo(h, "Parámetros"), False)[0], cuerpo)
            finally:
                if guardada is not None:
                    self.pila.append(guardada)
            return
        self.cuerpo_funcion(s, h, s.params or [], cuerpo, info, s.metodo_const, s.estatico,
                            self.lista_init_de(h))

    @staticmethod
    def lista_init_de(n):
        return next((h for h in n.hijos if h.tipo == "ListaInicialización"
                     and all(x.tipo == "Inicializa" for x in h.hijos)), None)

    # ─────────────────────── funciones ───────────────────────
    def misma_firma(self, a, b):
        def clave(p):
            t = p.tipo
            if not t.ref and not t.punteros:
                t = replace(t, const=False)
            elif t.punteros:
                t = replace(t, const=False)
            return str(t)
        return [clave(p) for p in (a or [])] == [clave(p) for p in (b or [])]

    def acepta_cantidad(self, f, n):
        ps = f.params or []
        mn = sum(1 for p in ps if p.defecto is None)
        return mn <= n and (f.variadico or n <= len(ps))

    def cuantos(self, f):
        ps = f.params or []
        return cuantos_txt(sum(1 for p in ps if p.defecto is None), None if f.variadico else len(ps))

    def leer_params(self, pn, revisar=True):
        params, variadico, con_defecto = [], False, False
        if pn is None:
            return params, variadico
        vistos = set()
        for p in pn.hijos:
            if p.tipo == "Variádico":
                variadico = True
                continue
            tn = self.hijo(p, "Tipo")
            t = self.tipo_de(tn) if revisar else self.resolver(texto_a_tipo(tn.valor), None, False)
            defecto = next((h for h in p.hijos if h is not tn), None)
            if revisar:
                x = self.pos_lexema(p, p.valor) if p.valor else p
                if t.nombre == "void" and not t.punteros:
                    self.error(tn, "Un parámetro no puede ser de tipo void",
                               "void solo se usa como tipo de retorno; si la función no recibe nada deja los paréntesis vacíos.",
                               "Lista de parámetros", "tipo de dato", "void")
                if p.valor and p.valor in vistos:
                    self.error(x, f"El parámetro '{p.valor}' está repetido",
                               "Cada parámetro debe tener un nombre distinto.", "Lista de parámetros",
                               "nombre nuevo", p.valor)
                if defecto is not None:
                    con_defecto = True
                    self.inicializar(sin_cv(t), defecto, p.valor or "parámetro", "Valor por defecto")
                elif con_defecto:
                    self.error(x, f"El parámetro '{p.valor}' necesita un valor por defecto porque uno anterior ya lo tiene",
                               "En C++ los parámetros con valor por defecto van al final de la lista.",
                               "Lista de parámetros", "valor por defecto", "sin valor")
            vistos.add(p.valor)
            params.append(Param(p.valor, t, defecto, p))
        return params, variadico

    def funcion(self, n):
        nombre = n.valor or ""
        if "::" in nombre:
            pre, _, corto = nombre.rpartition("::")
            if pre in self.clases or n.tipo in ("Constructor", "Destructor"):
                self.definir_fuera(n, pre, corto)
            elif pre in self.espacios:
                self.pila.append(self.espacios[pre])
                try:
                    self.funcion_libre(n, corto)
                finally:
                    self.pila.pop()
            else:
                self.error(self.pos_nombre(n), f"'{pre}' no es una clase ni un espacio de nombres declarado",
                           "Declara la clase (con el prototipo del método) antes de definir el método fuera de ella.",
                           "Definición de función", "clase declarada", pre)
            return
        self.funcion_libre(n, nombre)

    def funcion_libre(self, n, nombre):
        tn = self.hijo(n, "Tipo")
        ret = self.tipo_de(tn) if tn is not None else VOID
        params, variadico = self.leer_params(self.hijo(n, "Parámetros"))
        cuerpo = self.hijo(n, "Bloque")
        if nombre == "main" and self.pila[-1] is self.global_ and ret.nombre not in ("int", "?"):
            self.error(tn or self.pos_nombre(n), f"'main' debe devolver int, no {ret}",
                       "Escribe int main() { ... return 0; }.", "Función main", "int", str(ret))
            ret = INT                       # para no repetir el error en cada return
        s = self.declarar_funcion(nombre, ret, params, variadico, n, cuerpo is not None)
        if s is not None and cuerpo is not None:
            self.cuerpo_funcion(s, n, params, cuerpo)

    def declarar_funcion(self, nombre, ret, params, variadico, n, con_cuerpo, amb=None):
        amb = amb or self.pila[-1]
        x = self.pos_nombre(n)
        previos = amb.tabla.get(nombre, [])
        if previos and previos[0].categoria != "función":
            self.error(x, f"'{nombre}' ya fue declarado como {previos[0].categoria} (línea {previos[0].linea})",
                       "Usa otro nombre para la función.", "Declaración de función", "nombre nuevo",
                       f"'{nombre}' ya existe")
            return None
        for f in previos:
            if not (self.misma_firma(f.params, params) and f.variadico == variadico):
                continue
            if str(f.tipo) != str(ret) and "?" not in (f.tipo.nombre, ret.nombre):
                self.error(x, f"'{nombre}' ya se declaró en la línea {f.linea} devolviendo {f.tipo}; aquí devuelve {ret}",
                           "Usa el mismo tipo de retorno que en el prototipo: dos funciones no pueden "
                           "diferir solo en lo que devuelven.", "Declaración de función", str(f.tipo), str(ret))
                return None
            if con_cuerpo and f.definida:
                self.error(x, f"La función '{nombre}' ya fue definida en la línea {f.linea}",
                           "Elimina una de las dos definiciones, o cambia sus parámetros si quieres sobrecargarla.",
                           "Definición de función", "una sola definición", "definición repetida")
                return None
            if con_cuerpo:
                f.definida = True
                self.paso("Definición de función", x, f"prototipo de la línea {f.linea}", self.describir(f),
                          f"La definición de '{nombre}' coincide con su prototipo de la línea {f.linea}.")
            return f
        s = Simbolo(nombre, "función", ret, n.linea, n.columna, params=params, variadico=variadico,
                    definida=con_cuerpo)
        verbo = "la función" if con_cuerpo else "el prototipo de la función"
        self.registrar(s, x, amb, "Declaración de función" if con_cuerpo else "Prototipo de función",
                       f"Se registra {verbo} '{nombre}': {self.describir(s)}.")
        if nombre.startswith("operator"):
            self.ops_globales.setdefault(nombre[8:].strip(), []).append(s)
        return s

    def definir_fuera(self, n, pre, corto):
        """Método, constructor o destructor definido fuera de su clase: Clase::metodo(...) { }"""
        info = self.clases.get(pre)
        x = self.pos_nombre(n)
        if info is None:
            self.error(x, f"'{pre}' no es una clase declarada", "Declara la clase antes de definir sus métodos.",
                       "Definición fuera de la clase", "clase declarada", pre)
            return
        params, variadico = self.leer_params(self.hijo(n, "Parámetros"))
        calif = {c.valor for c in self.hijos(n, "Calificador")}
        cuerpo = self.hijo(n, "Bloque")
        tn = self.hijo(n, "Tipo")
        ret = self.tipo_de(tn) if tn is not None else VOID
        es_dtor = corto.startswith("~")
        es_ctor = not es_dtor and (n.tipo == "Constructor" or corto == pre)
        if es_ctor:
            cands, que = info.constructores, f"un constructor de '{pre}'"
        elif es_dtor:
            cands, que = ([info.destructor] if info.destructor else []), f"un destructor en '{pre}'"
        else:
            cands, que = [m for m in info.miembros.get(corto, []) if m.categoria == "método"], f"un método '{corto}'"
        s = None
        firma_def = "(" + ", ".join(str(p.tipo) for p in params) + ")" + (" const" if "const" in calif else "")
        if not cands:
            proto = f"{'' if es_ctor or es_dtor else str(ret) + ' '}{corto}{firma_def};"
            self.error(x, f"La clase '{pre}' no tiene declarado {que}",
                       f"Agrega el prototipo dentro de la clase: {proto}", "Definición fuera de la clase",
                       f"prototipo en '{pre}'", "no existe")
        else:
            iguales = [c for c in cands if self.misma_firma(c.params, params)
                       and (es_ctor or es_dtor or c.metodo_const == ("const" in calif))]
            if not iguales:
                self.error(x, f"'{pre}::{corto}{firma_def}' no coincide con la declaración de la clase",
                           f"Dentro de la clase se declaró como {corto}{self.firma(cands[0])}; usa los mismos "
                           f"parámetros" + (" y const." if cands[0].metodo_const != ("const" in calif) else "."),
                           "Definición fuera de la clase", self.firma(cands[0]), firma_def)
            else:
                s = iguales[0]
                if s.definida and cuerpo is not None:
                    self.error(x, f"'{pre}::{corto}' ya tiene cuerpo (línea {s.linea})",
                               "Elimina una de las dos definiciones.", "Definición fuera de la clase",
                               "una sola definición", "definición repetida")
                elif not es_ctor and not es_dtor and str(ret) != str(s.tipo) and "?" not in (ret.nombre, s.tipo.nombre):
                    self.error(tn or x, f"'{pre}::{corto}' devuelve {ret}, pero en la clase se declaró que devuelve {s.tipo}",
                               "Usa el mismo tipo de retorno que en la declaración de la clase.",
                               "Definición fuera de la clase", str(s.tipo), str(ret))
                else:
                    self.paso("Definición fuera de la clase", x, self.describir(s), firma_def,
                              f"'{pre}::{corto}' coincide con el prototipo declarado en la clase (línea {s.linea}).")
                s.definida = True
        if cuerpo is None:
            return
        if s is None:          # se revisa el cuerpo de todos modos para encontrar otros errores
            s = Simbolo(corto, "constructor" if es_ctor else "destructor" if es_dtor else "método",
                        Tipo(pre) if es_ctor else ret, n.linea, n.columna, params=params, clase=pre,
                        metodo_const="const" in calif)
        self.cuerpo_funcion(s, n, params, cuerpo, info, "const" in calif, s.estatico, self.lista_init_de(n))

    def cuerpo_funcion(self, s, nodo, params, cuerpo, clase=None, const=False, estatico=False, lista_init=None):
        anterior = (self.ctx, self.ciclos, self.switches)
        self.ctx = Contexto(s, clase, const, estatico)
        self.ciclos = self.switches = 0
        empujada = False
        if clase is not None and not any(a.clase is clase for a in self.pila):
            self.pila.append(Ambito(clase.nombre, clase.nombre, "clase", clase.miembros, clase))
            empujada = True
        ruta = f"{s.clase}::{s.nombre}" if s.clase and s.categoria != "función" else s.nombre
        if s.categoria == "constructor":
            ruta = f"{s.clase}::{s.clase}"
        corto = ruta.split("::")[-1]
        self.abrir(corto, "funcion", self.pos_nombre(nodo), ruta=ruta)
        try:
            amb = self.pila[-1]
            for p in params:
                if not p.nombre or p.nombre in amb.tabla:
                    continue
                ps = Simbolo(p.nombre, "parámetro", p.tipo, p.nodo.linea, p.nodo.columna)
                ps.linea, ps.columna = self.pos_lexema(p.nodo, p.nombre)[:2]
                self.registrar(ps, self.pos_lexema(p.nodo, p.nombre), amb, "Parámetro",
                               f"El parámetro '{p.nombre}' ({p.tipo}) se registra como variable local de {ruta}.")
            if s.categoria == "constructor" and clase is not None:
                self.lista_inicializacion(lista_init, clase, nodo)
            for st in cuerpo.hijos:
                self.seguro(self.sentencia, st)
            if (s.categoria in ("función", "método") and self.cat(s.tipo) not in ("void", "?")
                    and s.nombre != "main" and self.ctx.retornos == 0
                    and not any(x.tipo == "Throw" for x in cuerpo.preorden())):
                quien = "El método" if s.categoria == "método" else "La función"
                self.error(self.pos_nombre(nodo),
                           f"{quien} '{s.nombre}' debe devolver un valor de tipo {s.tipo}, pero no tiene ninguna sentencia return",
                           f"Agrega 'return' con un valor de tipo {s.tipo} al final, o cámbiala a void si no necesita devolver nada.",
                           "Sentencia return", f"return {s.tipo}", "sin return")
            self.cerrar(self.cierre(cuerpo))
        finally:
            if self.pila and self.pila[-1].tipo == "funcion":
                self.pila.pop()
            if empujada and self.pila and self.pila[-1].clase is clase:
                self.pila.pop()
            self.ctx, self.ciclos, self.switches = anterior

    def lista_inicializacion(self, lista, info, nodo):
        inicializados = set()
        for ini in (lista.hijos if lista is not None else []):
            nombre = ini.valor
            args_n = ini.hijos[0] if ini.hijos else None
            x = (ini.linea, ini.columna, len(nombre))
            campos = [m for m in info.miembros.get(nombre, []) if m.categoria == "atributo"]
            if campos:
                c = campos[0]
                if nombre in inicializados:
                    self.error(x, f"El atributo '{nombre}' se inicializa dos veces",
                               "Deja una sola inicialización por atributo.", "Lista de inicialización",
                               "una vez", "dos veces")
                inicializados.add(nombre)
                self.paso("Lista de inicialización", x, f"atributo de '{info.nombre}'", f"{nombre}: {c.tipo}",
                          f"'{nombre}' es un atributo de '{info.nombre}' ({c.tipo}); se le da su valor inicial.")
                if args_n is None:
                    continue
                if args_n.tipo == "ListaInicialización":
                    self.revisar_lista(sin_cv(c.tipo), args_n, nombre)
                    continue
                args = args_n.hijos
                if len(args) == 1 and args[0].tipo != "ListaInicialización":
                    self.init_expresion(c.tipo, args[0], nombre)
                else:
                    targs = [self.tipo_arg(a) for a in args]
                    cc = self.cat(c.tipo)
                    if cc == "clase":
                        self.construir(self.info_clase(c.tipo), args, targs, ini, nombre)
                    elif len(args) > 1 and cc not in {"contenedor", "cadena"} | LIBRES:
                        self.error(args[1], f"Demasiados valores para el atributo '{nombre}' ({c.tipo}); solo puede recibir uno",
                                   f"Deja un solo valor: {nombre}({self.texto(args[0])}).", "Lista de inicialización",
                                   "1 valor", f"{len(args)} valores")
            elif base(nombre) in info.bases:
                args = args_n.hijos if args_n is not None else []
                self.construir(self.clases[base(nombre)], args, [self.tipo_arg(a) for a in args], ini, None,
                               como_base=True)
            else:
                p = self.parecido(nombre, opciones=list(info.miembros))
                self.error(x, f"'{nombre}' no es un atributo de '{info.nombre}' ni una de sus clases base",
                           (f"¿Quisiste decir '{p}'? " if p else "") + "En la lista de inicialización solo van atributos de la clase o su clase base.",
                           "Lista de inicialización", "atributo de la clase", nombre)
        for nm, ms in info.miembros.items():
            for m in ms:
                if (m.categoria == "atributo" and not m.estatico and (m.tipo.const or m.tipo.ref)
                        and nm not in inicializados and not any(s is m for s, _ in info.inits)):
                    que = "constante" if m.tipo.const else "referencia"
                    self.error(self.pos_nombre(nodo), f"El constructor de '{info.nombre}' no inicializa el atributo {que} '{nm}'",
                               f"Inicialízalo en la lista de inicialización: {info.nombre}(...) : {nm}(valor) {{ }}",
                               "Constructor", f"'{nm}' inicializado", "sin inicializar")

    # ─────────────────────── variables ───────────────────────
    def declarar_variables(self, n, categoria, info=None, acceso="public"):
        mods = self.especificadores(n)
        tn = self.hijo(n, "Tipo")
        if tn is None:
            return
        t = self.tipo_de(tn)
        if "constexpr" in mods and not t.punteros:
            t = replace(t, const=True)
        for v in self.hijos(n, "Variable"):
            self.seguro(self.declarar_variable, v, t, mods, categoria, tn, info, acceso)

    def nombre_variable(self, v):
        i = self.indice_tok.get((v.linea, v.columna))
        if i is not None:
            tok = self.toks[i]
            if tok.tipo == "IDENTIFICADOR" and v.valor.endswith(tok.lexema) and "::" not in v.valor:
                return tok.lexema, v.valor[:len(v.valor) - len(tok.lexema)]
        m = re.match(r"^([*&]+(?:const)?[*&]*)?(.*)$", v.valor)
        return m.group(2), (m.group(1) or "")

    def declarar_variable(self, v, base_t, mods, categoria, tn=None, info=None, acceso="public"):
        nombre, prefijo = self.nombre_variable(v)
        if "::" in nombre:
            return self.definir_estatico(v, nombre, base_t)
        x = (v.linea, v.columna, len(nombre))
        t = base_t
        nptr = prefijo.count("*")
        if nptr:
            t = (replace(t, punteros=t.punteros + nptr, const="const" in prefijo) if t.punteros
                 else Tipo(t.nombre, nptr, False, "const" in prefijo, t.const, t.dims))
        if "&" in prefijo:
            t = replace(t, ref=True)
        dims, tam_invalido = [], False
        for d in self.hijos(v, "Dimensión"):
            if not d.hijos:
                dims.append(None)
                continue
            td = self.expr(d.hijos[0])
            val = self.valor_constante(d.hijos[0])
            if self.cat(td) not in ENTERAS | LIBRES:
                self.error(d.hijos[0], f"El tamaño del arreglo '{nombre}' debe ser un número entero; se encontró {td}",
                           "Usa un número entero o una constante entera, por ejemplo: int datos[10];",
                           "Declaración de arreglo", "entero", str(td))
                dims.append(None)
                tam_invalido = True
            elif isinstance(val, (int, float)) and val <= 0:
                self.error(d.hijos[0], f"El tamaño del arreglo '{nombre}' debe ser mayor que cero (se indicó {val})",
                           "Indica cuántos elementos tendrá el arreglo, por ejemplo: int datos[10];",
                           "Declaración de arreglo", "tamaño > 0", str(val))
                dims.append(None)
                tam_invalido = True
            else:
                dims.append(val if isinstance(val, int) else None)
        if dims:
            t = replace(t, dims=tuple(dims) + t.dims)
        init = next((h for h in reversed(v.hijos) if h.tipo != "Dimensión"), None)
        amb = self.pila[-1]
        prev = amb.tabla.get(nombre)
        if prev:
            p = prev[0]
            sug = "Usa otro nombre o elimina la declaración repetida."
            if p.categoria in ("variable", "parámetro"):
                sug += f" Si querías cambiar su valor, quita el tipo: {nombre} = ...;"
            self.error(x, f"'{nombre}' ya fue declarado en este ámbito (línea {p.linea}, como {p.categoria})",
                       sug, "Redeclaración", "nombre nuevo", f"'{nombre}' ya existe")
            if init is not None:
                self.tipo_arg(init)
            return
        hecho = False
        if t.nombre == "auto":
            hecho = True
            elems = init.hijos if init is not None and init.tipo in ("ListaInicialización", "Argumentos") else None
            fuente = init if elems is None else (elems[0] if len(elems) == 1 else None)
            if init is None:
                self.error(x, f"'{nombre}' se declaró con auto, pero no tiene valor inicial",
                           "auto necesita un valor para deducir el tipo, por ejemplo: auto total = 0;",
                           "Deducción de tipo", "valor inicial", "sin valor")
                t = DESCONOCIDO
            elif fuente is None or fuente.tipo == "ListaInicialización":
                self.tipo_arg(init)
                t = DESCONOCIDO
            else:
                ti = self.expr(fuente)
                if self.cat(ti) == "void":
                    self.error(fuente, f"No se puede deducir el tipo de '{nombre}': la expresión no devuelve ningún valor (void)",
                               "Usa auto solo con expresiones que devuelvan un valor.", "Deducción de tipo",
                               "valor", "void")
                    t = DESCONOCIDO
                else:
                    d = decaer(ti) if ti.dims else ti
                    t = Tipo(d.nombre, max(d.punteros, t.punteros), t.ref, t.const, d.const_base)
                    self.paso("Deducción de tipo", fuente, "tipo del valor", str(t),
                              f"auto toma el tipo del valor inicial: '{nombre}' será {t}.")
        if t.nombre == "void" and not t.punteros:
            self.error(tn or x, f"La variable '{nombre}' no puede ser de tipo void",
                       "void solo se usa para funciones que no devuelven nada; usa int, double, string, etc.",
                       "Declaración de variable", "tipo de dato", "void")
            t = DESCONOCIDO
        valor = None
        if not hecho:
            if init is None:
                if not tam_invalido:
                    self.sin_inicializador(t, nombre, x, mods, categoria)
            elif categoria == "atributo":
                info.inits.append((None, init))          # se revisa en la segunda pasada
            elif init.tipo == "Argumentos":
                self.init_argumentos(t, init, nombre, x)
            elif init.tipo == "ListaInicialización":
                if t.dims and t.dims[0] is None and init.hijos and not tam_invalido:
                    t = replace(t, dims=(len(init.hijos),) + t.dims[1:])
                self.revisar_lista(sin_cv(t) if not t.dims else t, init, nombre)
            else:
                t = self.init_expresion(t, init, nombre)
        if init is not None and (t.const or "constexpr" in mods) and self.cat(t) in NUMERICAS:
            fuente = init.hijos[0] if init.tipo in ("ListaInicialización", "Argumentos") and len(init.hijos) == 1 else init
            valor = self.valor_constante(fuente)
        s = Simbolo(nombre, categoria, t, v.linea, v.columna, valor=valor,
                    clase=info.nombre if info is not None else "", acceso=acceso, estatico="static" in mods)
        if categoria == "atributo" and info is not None and info.inits and info.inits[-1][0] is None:
            info.inits[-1] = (s, info.inits[-1][1])
        regla = {"variable": "Declaración de variable", "atributo": "Declaración de atributo"}.get(categoria, "Declaración")
        donde = f"de '{info.nombre}' ({acceso})" if info is not None else f"en el ámbito {amb.nombre}"
        self.registrar(s, x, amb, regla, f"Se agrega '{nombre}' ({t}) a la tabla de símbolos {donde}.")

    def definir_estatico(self, v, nombre, t):
        """int Clase::contador = 0;  (definición de un atributo static fuera de la clase)"""
        pre, _, ult = nombre.rpartition("::")
        info = self.clases.get(pre)
        x = (v.linea, v.columna, len(nombre))
        ms = [m for m in self.miembro(info, ult) if m.categoria == "atributo"] if info else []
        if not ms or not ms[0].estatico:
            self.error(x, f"'{pre}' no tiene un atributo static llamado '{ult}'",
                       "Declara el atributo como static dentro de la clase antes de definirlo afuera.",
                       "Atributo static", "atributo static declarado", nombre)
            return
        init = next((h for h in reversed(v.hijos) if h.tipo != "Dimensión"), None)
        if init is not None and init.tipo not in ("Argumentos", "ListaInicialización"):
            self.inicializar(sin_cv(ms[0].tipo), init, nombre, "Atributo static")

    def sin_inicializador(self, t, nombre, x, mods, categoria):
        if categoria == "atributo" or "extern" in mods:
            return
        if t.ref:
            self.error(x, f"La referencia '{nombre}' debe inicializarse al declararse",
                       f"Indica a qué variable se refiere: {t} {nombre} = otraVariable;",
                       "Declaración de referencia", "variable a la que se refiere", "sin valor")
        elif t.const:
            self.error(x, f"La constante '{nombre}' debe tener un valor inicial",
                       f"Asígnale el valor al declararla: {t} {nombre} = valor;",
                       "Declaración de constante", "valor inicial", "sin valor")
        elif t.dims and t.dims[0] is None:
            self.error(x, f"Falta el tamaño del arreglo '{nombre}'",
                       f"Indica el tamaño entre corchetes o dale valores iniciales: {t.nombre} {nombre}[] = {{1, 2, 3}};",
                       "Declaración de arreglo", "tamaño o valores", "[]")
        elif self.cat(t) == "clase" and not t.dims:
            info = self.info_clase(t)
            if info is not None and not info.completa:
                self.error(x, f"No se puede crear '{nombre}' porque '{info.nombre}' solo está declarada, no definida",
                           f"Define la clase completa (class {info.nombre} {{ ... }};) antes de crear objetos.",
                           "Creación de objeto", "clase definida", "solo declarada")
            else:
                self.construir(info, [], [], x, nombre)

    def init_argumentos(self, t, init, nombre, x):
        """Inicialización con paréntesis: Cuenta c("Ana", 50);  int n(5);"""
        args = init.hijos
        targs = [self.tipo_arg(a) for a in args]
        c = self.cat(t)
        if c == "clase" and not t.dims:
            self.construir(self.info_clase(t), args, targs, x, nombre)
        elif c == "arreglo":
            self.error(x, f"Un arreglo no se inicializa con paréntesis; usa llaves",
                       f"Por ejemplo: {t.nombre} {nombre}[] = {{1, 2, 3}};", "Inicialización", "{ ... }", "( ... )")
        elif c in {"contenedor", "cadena", "flujo"} | LIBRES or not args:
            return
        elif len(args) > 1:
            self.error(args[1], f"Demasiados valores para inicializar '{nombre}' ({t}); solo puede recibir uno",
                       f"Deja un solo valor: {t} {nombre}({self.texto(args[0])});", "Inicialización",
                       "1 valor", f"{len(args)} valores")
        else:
            self.revisar_referencia(t, args[0], targs[0], nombre) or \
                self.compatible_o_error(sin_cv(t), targs[0], args[0], "init", nombre, "Inicialización")

    def revisar_referencia(self, t, nodo, ti, nombre):
        """Errores propios de las referencias no const. Devuelve True si reportó algo."""
        if not t.ref or t.const or self.cat(t) in LIBRES or self.cat(ti) in LIBRES:
            return False
        if not self.es_lvalue(nodo):
            self.error(nodo, f"La referencia '{nombre}' ({t}) debe referirse a una variable, no a un valor",
                       f"Usa una variable: {t} {nombre} = otraVariable; o declara la referencia como const.",
                       "Declaración de referencia", "variable", self.texto(nodo))
            return True
        if self.cat(t) in NUMERICAS and sin_cv(t).nombre != sin_cv(ti).nombre:
            self.error(nodo, f"La referencia '{nombre}' ({t}) solo puede referirse a una variable {sin_cv(t)}, y '{self.texto(nodo)}' es {ti}",
                       f"Usa una variable de tipo {sin_cv(t)} o quita el '&'.", "Declaración de referencia",
                       str(sin_cv(t)), str(ti))
            return True
        return False

    def init_expresion(self, t, init, nombre):
        """Inicialización con '='. Devuelve el tipo final (un char[] puede tomar su tamaño del texto)."""
        c = self.cat(t)
        if c == "arreglo":
            ti = self.expr(init)
            if t.nombre in ("char", "wchar_t") and init.tipo == "LiteralCadena" and len(t.dims) == 1:
                n = largo_cadena(init.valor)
                if n is not None:
                    if t.dims[0] is None:
                        return replace(t, dims=(n,))
                    if n > t.dims[0]:
                        self.error(init, f"El texto {self.texto(init)} ocupa {n} caracteres (con el '\\0' final) y '{nombre}' solo tiene {t.dims[0]}",
                                   f"Aumenta el tamaño del arreglo a {n} o más, o usa string.",
                                   "Inicialización de arreglo", f"≤ {t.dims[0]} caracteres", f"{n} caracteres")
                return t
            self.error(init, f"El arreglo '{nombre}' no se puede inicializar con un valor {ti}; usa una lista entre llaves",
                       f"Por ejemplo: {t.nombre} {nombre}[] = {{1, 2, 3}};", "Inicialización de arreglo",
                       "{ ... }", str(ti))
            return t
        if init.tipo == "ListaInicialización":
            self.revisar_lista(sin_cv(t), init, nombre)
            return t
        ti = self.expr(init)
        if not self.revisar_referencia(t, init, ti, nombre):
            self.compatible_o_error(sin_cv(t), ti, init, "init", nombre, "Inicialización")
        return t

    def inicializar(self, dest, nodo, nombre, regla="Inicialización"):
        if nodo.tipo == "ListaInicialización":
            self.revisar_lista(dest, nodo, nombre)
            return
        t = self.expr(nodo)
        if self.cat(dest) == "arreglo" and dest.nombre in ("char", "wchar_t") and nodo.tipo == "LiteralCadena":
            n = largo_cadena(nodo.valor)
            if n is not None and dest.dims[0] is not None and n > dest.dims[0]:
                self.error(nodo, f"El texto ocupa {n} caracteres y '{nombre}' solo tiene {dest.dims[0]}",
                           "Usa un texto más corto o un arreglo más grande.", regla, f"≤ {dest.dims[0]}", str(n))
            return
        self.compatible_o_error(dest, t, nodo, "init", nombre, regla)

    def revisar_lista(self, dest, lista, nombre):
        """Inicialización con llaves: arreglos, vector, struct, clases y valores simples."""
        elems = list(lista.hijos)
        c = self.cat(dest)
        if c == "arreglo":
            d = dest.dims[0]
            elem = replace(dest, dims=dest.dims[1:])
            if elem.dims and not any(e.tipo == "ListaInicialización" for e in elems):
                total = math.prod(x for x in dest.dims) if None not in dest.dims else None
                if total is not None and len(elems) > total:
                    self.error(elems[total], f"Demasiados valores para '{nombre}': caben {total} y la lista trae {len(elems)}",
                               "Quita los valores que sobran o aumenta el tamaño del arreglo.",
                               "Lista de inicialización", f"≤ {total} valores", f"{len(elems)} valores")
                for e in elems:
                    self.inicializar(Tipo(dest.nombre, dest.punteros, False, False, dest.const_base), e, f"{nombre}[…]",
                                     "Lista de inicialización")
                return
            if d is not None and len(elems) > d:
                self.error(elems[d], f"Demasiados valores para '{nombre}': el arreglo tiene {plural(d, 'elemento')} y la lista trae {len(elems)}",
                           "Quita los valores que sobran o aumenta el tamaño del arreglo.",
                           "Lista de inicialización", f"≤ {d} valores", f"{len(elems)} valores")
            if self.cat(elem) == "clase" and not any(e.tipo == "ListaInicialización" for e in elems) \
                    and not self.info_clase(elem).constructores:
                for e in elems:
                    self.tipo_arg(e)
                return
            for i, e in enumerate(elems):
                self.inicializar(replace(elem, const=False), e, f"{nombre}[{i}]", "Lista de inicialización")
            return
        if c == "contenedor":
            b = base(dest.nombre)
            if b in ("map", "unordered_map", "multimap"):
                k, val = self.elemento_contenedor(dest, 0), self.elemento_contenedor(dest, 1)
                for e in elems:
                    if e.tipo == "ListaInicialización" and len(e.hijos) == 2:
                        self.inicializar(k, e.hijos[0], f"clave de {nombre}", "Lista de inicialización")
                        self.inicializar(val, e.hijos[1], f"valor de {nombre}", "Lista de inicialización")
                    else:
                        self.tipo_arg(e)
            elif b in SECUENCIAS:
                if b == "array":
                    args = args_plantilla(dest.nombre)
                    tam = entero_literal(args[1]) if len(args) > 1 else None
                    if tam is not None and len(elems) > tam:
                        self.error(elems[tam], f"Demasiados valores para '{nombre}': el array tiene {tam} elementos y la lista trae {len(elems)}",
                                   "Quita los valores que sobran.", "Lista de inicialización", f"≤ {tam}", str(len(elems)))
                el = self.elemento_contenedor(dest)
                for i, e in enumerate(elems):
                    self.inicializar(el, e, f"{nombre}[{i}]", "Lista de inicialización")
            else:
                for e in elems:
                    self.tipo_arg(e)
            return
        if c == "clase":
            info = self.info_clase(dest)
            if info.constructores or info.puras:
                self.construir(info, elems, [self.tipo_arg(e) for e in elems], lista, nombre)
                return
            campos = sorted((m for ms in info.miembros.values() for m in ms
                             if m.categoria == "atributo" and not m.estatico), key=lambda m: (m.linea, m.columna))
            if len(elems) > len(campos):
                self.error(elems[len(campos)] if campos else lista,
                           f"Demasiados valores para '{nombre}': '{info.nombre}' tiene {plural(len(campos), 'atributo')} y la lista trae {len(elems)}",
                           ("Los valores se asignan en orden a: " + ", ".join(m.nombre for m in campos) + ".") if campos
                           else f"'{info.nombre}' no tiene atributos.", "Lista de inicialización",
                           f"≤ {len(campos)} valores", f"{len(elems)} valores")
            for e, m in zip(elems, campos):
                self.inicializar(sin_cv(m.tipo) if not m.tipo.dims else m.tipo, e, f"{nombre}.{m.nombre}",
                                 "Lista de inicialización")
            for e in elems[len(campos):]:
                self.tipo_arg(e)
            return
        if c in LIBRES | {"flujo", "cadena", "lista"}:
            for e in elems:
                self.tipo_arg(e)
            return
        if len(elems) > 1:
            self.error(elems[1], f"Demasiados valores para '{nombre}' ({dest}): entre llaves solo puede ir un valor",
                       f"Deja un solo valor: {{{self.texto(elems[0])}}}.", "Lista de inicialización",
                       "1 valor", f"{len(elems)} valores")
        if not elems:
            return
        e = elems[0]
        if e.tipo == "ListaInicialización":
            self.tipo_arg(e)
            return
        t = self.expr(e)
        if c in ("entero", "bool") and self.cat(t) == "real":
            self.error(e, f"Conversión con pérdida: no se puede guardar {t} en '{nombre}' ({dest}) usando llaves",
                       "Dentro de llaves C++ no permite perder los decimales; usa un entero, "
                       "static_cast<int>(...) o inicializa con '='.", "Lista de inicialización", str(dest), str(t))
        else:
            self.compatible_o_error(dest, t, e, "init", nombre, "Lista de inicialización")

    def construir(self, info, args, targs, x, nombre_var=None, como_base=False):
        """Crear un objeto: revisa clase abstracta y que exista un constructor adecuado."""
        if info is None:
            return
        if info.puras and not como_base:
            self.error(x, f"No se puede crear un objeto de '{info.nombre}' porque es una clase abstracta",
                       f"'{info.nombre}' tiene métodos virtuales puros sin implementar ({', '.join(sorted(info.puras))}); "
                       f"crea un objeto de una clase derivada que los implemente.",
                       "Creación de objeto", "clase concreta", "clase abstracta")
            return
        n = len(targs)
        var = nombre_var or "obj"
        if n == 1 and self.cat(targs[0]) == "clase" and self.hereda(targs[0].nombre, info.nombre):
            return                                     # constructor de copia implícito
        ctors = [c for c in info.constructores if not c.borrado]
        if not info.constructores:
            if n == 0 or (n == 1 and self.cat(targs[0]) in LIBRES):
                return
            self.error(x, f"'{info.nombre}' no tiene un constructor que reciba {plural(n, 'argumento')}",
                       f"Declara un constructor {info.nombre}(...) en la clase, o inicializa con llaves: "
                       f"{info.nombre} {var} = {{...}};", "Constructor", "constructor declarado",
                       "(" + ", ".join(str(t) for t in targs) + ")")
            return
        if n == 0 and not any(self.acepta_cantidad(c, 0) for c in ctors):
            ejemplo = ", ".join(p.nombre or "valor" for p in (ctors[0].params if ctors else []))
            self.error(x, f"'{info.nombre}' no tiene un constructor sin parámetros",
                       f"Pasa los datos al crear el objeto: {info.nombre} {var}({ejemplo}); o agrega un "
                       f"constructor {info.nombre}() a la clase.", "Constructor", "constructor sin parámetros",
                       self.firma(ctors[0]) if ctors else "—")
            return
        if not ctors:
            self.error(x, f"Los constructores de '{info.nombre}' están eliminados (= delete)",
                       "Quita '= delete' o usa otra forma de crear el objeto.", "Constructor", "constructor", "= delete")
            return
        f = self.resolver_llamada(ctors, args, targs, x, f"el constructor de '{info.nombre}'", info.nombre)
        if f is not None and f.acceso != "public" and not (self.ctx and self.ctx.clase is info):
            self.error(x, f"El constructor {info.nombre}{self.firma(f)} es {f.acceso} y no se puede usar desde aquí",
                       "Declara el constructor en la sección public de la clase.", "Control de acceso",
                       "constructor public", f"constructor {f.acceso}")

    # ─────────────────────── llamadas ───────────────────────
    def tipo_arg(self, a):
        if a.tipo == "ListaInicialización":
            for e in a.hijos:
                self.tipo_arg(e)
            self.tipos[a.id] = LISTA
            return LISTA
        return self.expr(a)

    def problema_argumento(self, p, t, a):
        """None si el argumento sirve para el parámetro; si no, (mensaje, sugerencia)."""
        pt = p.tipo
        if t.nombre == "{}":
            return None
        if pt.ref and not pt.const and self.cat(pt) not in LIBRES and self.cat(t) not in LIBRES:
            nom = f" '{p.nombre}'" if p.nombre else ""
            if not self.es_lvalue(a):
                return (f"el parámetro{nom} es una referencia ({pt}) y necesita una variable, pero se envía el valor {self.texto(a)}",
                        "Guarda el valor en una variable y pasa la variable, o declara el parámetro como const.")
            if t.const:
                return (f"'{self.texto(a)}' es constante y el parámetro{nom} ({pt}) permitiría modificarlo",
                        "Declara el parámetro como const o pasa una variable que no sea const.")
            if self.cat(pt) in NUMERICAS and sin_cv(pt).nombre != sin_cv(t).nombre:
                return (f"el parámetro{nom} es {pt} y solo acepta una variable {sin_cv(pt)}, pero se envía {t}",
                        f"Pasa una variable de tipo {sin_cv(pt)}.")
        if not self.compatible(sin_cv(pt) if not pt.punteros else replace(pt, ref=False, const=False), t, a, "param"):
            return f"se esperaba {pt} y se envía {t}", self.sugerencia_tipos(sin_cv(pt), t, a)
        return None

    def puntaje(self, f, targs, args):
        total = 0
        for p, t, a in zip(f.params or [], targs, args):
            if self.problema_argumento(p, t, a):
                return None
            pt = sin_cv(p.tipo)
            if t.nombre == "{}" or self.cat(t) in LIBRES:
                total += 1
            elif pt.nombre == t.nombre and niveles(pt) == niveles(decaer(t)):
                total += 0
            elif self.cat(pt) in NUMERICAS and self.cat(t) in NUMERICAS:
                total += 1
            else:
                total += 2
        return total

    def resolver_llamada(self, cands, args, targs, x, sujeto, nombre):
        n = len(targs)
        encontrado = "(" + ", ".join(str(t) for t in targs) + ")"
        viables = [f for f in cands if self.acepta_cantidad(f, n)]
        if not viables:
            if len(cands) == 1:
                f = cands[0]
                falta = n < sum(1 for p in (f.params or []) if p.defecto is None)
                self.error(x, f"{cap(sujeto)} espera {self.cuantos(f)} y recibe {n}",
                           f"Se declaró como {nombre}{self.firma(f)} (línea {f.linea}). "
                           + ("Agrega los argumentos que faltan." if falta else "Quita los argumentos que sobran."),
                           "Llamada a función", self.firma(f), encontrado)
            else:
                self.error(x, f"Ninguna versión {de(sujeto)} recibe {plural(n, 'argumento')}",
                           "Versiones declaradas: " + "; ".join(f"{nombre}{self.firma(f)}" for f in cands) + ".",
                           "Llamada a función", " | ".join(self.firma(f) for f in cands), encontrado)
            return None
        mejor, puntos = None, None
        for f in viables:
            p = self.puntaje(f, targs, args)
            if p is not None and (puntos is None or p < puntos):
                mejor, puntos = f, p
        if mejor is not None:
            self.paso("Llamada a función", x, self.firma(mejor), encontrado,
                      f"Los argumentos {encontrado} coinciden con {nombre}{self.firma(mejor)}.")
            return mejor
        if len(viables) > 1:
            self.error(x, f"Ninguna versión {de(sujeto)} acepta los argumentos {encontrado}",
                       "Versiones declaradas: " + "; ".join(f"{nombre}{self.firma(f)}" for f in viables) + ".",
                       "Llamada a función", " | ".join(self.firma(f) for f in viables), encontrado)
            return viables[0]
        f = viables[0]
        for i, (p, t, a) in enumerate(zip(f.params or [], targs, args), 1):
            motivo = self.problema_argumento(p, t, a)
            if motivo:
                self.error(a, f"Argumento {i} {de(sujeto)}: {motivo[0]}", motivo[1], "Llamada a función",
                           str(p.tipo), str(t))
                break
        return f

    def llamar_biblioteca(self, s, args, targs, x, nombre):
        if s.lib is None:
            return s.tipo if s.es_tipo else DESCONOCIDO
        mn, mx, clase = s.lib
        n = len(targs)
        if n < mn or (mx is not None and n > mx):
            self.error(x, f"'{nombre}' recibe {cuantos_txt(mn, mx)} y aquí recibe {n}",
                       f"Ejemplo de uso: {EJEMPLOS.get(nombre, nombre + '(...)')}.", "Llamada a función",
                       cuantos_txt(mn, mx), plural(n, "argumento"))
            return s.tipo
        for i, (t, a) in enumerate(zip(targs, args), 1):
            c = self.cat(t)
            if c in LIBRES or t.nombre == "{}":
                continue
            if clase == "num" and c not in NUMERICAS:
                self.error(a, f"'{nombre}' necesita un número en el argumento {i}, pero recibe {t}",
                           "Si el valor es texto conviértelo primero con stoi() o stod()." if c == "cadena" or es_texto_c(t)
                           else f"Ejemplo de uso: {EJEMPLOS.get(nombre, nombre + '(numero)')}.",
                           "Llamada a función", "número", str(t))
                return s.tipo
            if clase == "cad" and c != "cadena" and not es_texto_c(t):
                self.error(a, f"'{nombre}' convierte texto a número, pero el argumento {i} es {t}",
                           "Pasa un string, por ejemplo: stoi(\"25\"). Si ya es un número no necesitas convertirlo.",
                           "Llamada a función", "string", str(t))
                return s.tipo
            if clase == "cstr" and not es_texto_c(t):
                self.error(a, f"'{nombre}' trabaja con cadenas de C (char*), pero el argumento {i} es {t}",
                           "Con string usa sus métodos (.size(), .compare(), ...) o conviértelo con .c_str().",
                           "Llamada a función", "char*", str(t))
                return s.tipo
        ret = s.tipo
        if nombre in ("max", "min") and n == 2:
            a, b = targs
            if self.cat(a) in NUMERICAS and self.cat(b) in NUMERICAS:
                if sin_cv(a).nombre != sin_cv(b).nombre:
                    self.error(x, f"{nombre}() necesita dos valores del mismo tipo, pero recibe {sin_cv(a)} y {sin_cv(b)}",
                               f"Convierte uno de los dos para que coincidan, por ejemplo: {nombre}((double) a, b).",
                               "Llamada a función", f"({sin_cv(a)}, {sin_cv(a)})", f"({sin_cv(a)}, {sin_cv(b)})")
                ret = sin_cv(a)
            elif self.cat(a) == "cadena" and self.cat(b) == "cadena":
                ret = STRING
        elif nombre in ("abs", "fabs") and targs and self.cat(targs[0]) == "real":
            ret = DOUBLE
        elif nombre == "getline" and n >= 2:
            c = self.cat(targs[1])
            if c not in LIBRES and c != "cadena":
                self.error(args[1], f"getline guarda una línea de texto en un string, pero '{self.texto(args[1])}' es {targs[1]}",
                           "Declara la variable como string, o usa cin >> para leer números.",
                           "Llamada a función", "string", str(targs[1]))
            elif not self.es_lvalue(args[1]):
                self.error(args[1], "getline necesita una variable string donde guardar el texto",
                           "Pasa el nombre de una variable: getline(cin, texto);", "Llamada a función",
                           "variable", self.texto(args[1]))
        self.paso("Llamada a función", x, "función de biblioteca", f"{nombre} → {ret}",
                  f"'{nombre}' es una función de la biblioteca estándar" + (f"; devuelve {ret}." if ret.nombre != "?" else "."))
        return ret

    # ═══════════════════════════ sentencias ═══════════════════════════
    def sentencia(self, n):
        if n is None:
            return
        f = SENTENCIAS.get(n.tipo)
        if f is not None:
            f(self, n)
        elif n.tipo in ("Clase", "Estructura", "Unión"):
            self.clase(n)
        elif n.tipo == "Enumeración":
            self.enumeracion(n)
        elif n.tipo == "Typedef":
            self.typedef(n)
        elif n.tipo == "DirectivaUsing":
            self.using(n)
        elif n.tipo == "UsingNamespace":
            self.using_namespace(n)
        else:
            self.expr(n)

    def subsentencia(self, x, nombre):
        if x is None:
            return
        if x.tipo == "Bloque":
            self.abrir(nombre, "bloque", (x.linea, x.columna, 1))
            for h in x.hijos:
                self.seguro(self.sentencia, h)
            self.cerrar(self.cierre(x))
        elif x.tipo == "DeclaraciónVariable":
            self.abrir(nombre, "bloque", None, paso=False)
            self.sentencia(x)
            self.cerrar(paso=False)
        else:
            self.sentencia(x)

    def s_bloque(self, n):
        self.subsentencia(n, "bloque")

    def s_declaracion(self, n):
        self.declarar_variables(n, "variable")

    def s_expresion(self, n):
        for h in n.hijos:
            self.expr(h)

    def condicion(self, c, palabra):
        if c is None or not c.hijos:
            return
        x = c.hijos[0]
        t = self.expr(x)
        if self.a_bool(t):
            self.paso("Condición", x, "bool", str(t),
                      f"La condición del {palabra} ({t}) se puede evaluar como verdadero o falso.")
            return
        k = self.cat(t)
        if k == "void":
            sug = "La función no devuelve ningún valor (void), así que no puede usarse como condición."
        elif k == "cadena":
            sug = 'Compara el texto con otro, por ejemplo: if (nombre == "Ana"), o revisa si está vacío con !nombre.empty().'
        elif k == "contenedor":
            sug = "Usa !contenedor.empty() para saber si tiene elementos."
        else:
            sug = "Usa una comparación que dé verdadero o falso, por ejemplo: (x > 0)."
        self.error(x, f"La condición del {palabra} debe poder evaluarse como verdadero o falso, pero '{self.texto(x)}' es {t}",
                   sug, "Condición", "bool", str(t))

    def s_if(self, n):
        cond = self.hijo(n, "Condición")
        self.condicion(cond, "if")
        cuerpo = next((h for h in n.hijos if h is not cond and h.tipo != "Else"), None)
        self.subsentencia(cuerpo, "if")
        e = self.hijo(n, "Else")
        if e is not None and e.hijos:
            self.subsentencia(e.hijos[0], "else")

    def s_while(self, n):
        cond = self.hijo(n, "Condición")
        self.condicion(cond, "while")
        self.ciclos += 1
        self.subsentencia(next((h for h in n.hijos if h is not cond), None), "while")
        self.ciclos -= 1

    def s_do(self, n):
        cond = self.hijo(n, "Condición")
        self.ciclos += 1
        self.subsentencia(next((h for h in n.hijos if h is not cond), None), "do")
        self.ciclos -= 1
        self.condicion(cond, "do-while")

    def cuerpo_en_ambito(self, cuerpo):
        if cuerpo is None:
            return
        if cuerpo.tipo == "Bloque":
            for h in cuerpo.hijos:
                self.seguro(self.sentencia, h)
        else:
            self.sentencia(cuerpo)

    def s_for(self, n):
        ini, cond, inc = self.hijo(n, "Inicialización"), self.hijo(n, "Condición"), self.hijo(n, "Incremento")
        cuerpo = next((h for h in n.hijos if h.tipo not in ("Inicialización", "Condición", "Incremento")), None)
        self.abrir("for", "bloque", (n.linea, n.columna, 3))
        for h in (ini.hijos if ini is not None else []):
            if h.tipo == "DeclaraciónVariable":
                self.declarar_variables(h, "variable")
            else:
                self.expr(h)
        self.condicion(cond, "for")
        for h in (inc.hijos if inc is not None else []):
            self.expr(h)
        self.ciclos += 1
        self.cuerpo_en_ambito(cuerpo)
        self.ciclos -= 1
        self.cerrar(self.cierre(cuerpo) if cuerpo is not None and cuerpo.tipo == "Bloque" else (n.linea, n.columna, 3))

    def s_for_rango(self, n):
        tn = self.hijo(n, "Tipo")
        resto = [h for h in n.hijos if h is not tn]
        rango = resto[0] if resto else None
        cuerpo = resto[1] if len(resto) > 1 else None
        self.abrir("for", "bloque", (n.linea, n.columna, 3))
        tr = self.tipo_arg(rango) if rango is not None else DESCONOCIDO
        c, txt = self.cat(tr), self.texto(rango)
        elem = DESCONOCIDO
        if c == "arreglo":
            elem = elemento(tr)
        elif c == "cadena":
            elem = replace(CHAR, const=tr.const)
        elif c == "contenedor":
            b = base(tr.nombre)
            if b in ("stack", "queue", "priority_queue"):
                self.error(rango, f"Un {b} no se puede recorrer con un for de rango",
                           "Saca los elementos uno por uno con un while (top()/front() y pop()).",
                           "Ciclo for de rango", "arreglo o contenedor recorrible", str(tr))
            elif b not in ("map", "unordered_map", "multimap"):
                e = self.elemento_contenedor(tr)
                elem = replace(e, const=tr.const or e.const)
        elif c == "clase" and not self.miembro(self.info_clase(tr), "begin"):
            self.error(rango, f"No se puede recorrer '{txt}' con un for de rango porque la clase '{base(tr.nombre)}' no tiene begin() y end()",
                       "Recorre sus datos internos (por ejemplo un vector que tenga como atributo).",
                       "Ciclo for de rango", "arreglo o contenedor", str(tr))
        elif c == "puntero":
            self.error(rango, f"Un puntero ('{txt}') no se puede recorrer con un for de rango porque no se sabe cuántos elementos hay",
                       "Usa un for clásico con un índice y el tamaño.", "Ciclo for de rango", "arreglo o contenedor", str(tr))
        elif c not in LIBRES | {"lista", "clase"}:
            self.error(rango, f"No se puede recorrer '{txt}' con un for de rango porque es {tr}",
                       "El for de rango solo funciona con arreglos, string y contenedores como vector.",
                       "Ciclo for de rango", "arreglo o contenedor", str(tr))
        declarado = self.tipo_de(tn)
        if declarado.nombre == "auto":
            t = (DESCONOCIDO if elem.nombre == "?" else
                 Tipo(elem.nombre, elem.punteros, declarado.ref,
                      declarado.const or (declarado.ref and elem.const), elem.const_base))
        else:
            t = declarado
            if declarado.ref and not declarado.const and elem.const and self.cat(elem) not in LIBRES:
                self.error(tn, f"Los elementos de '{txt}' son constantes y '{n.valor}' es una referencia que permitiría modificarlos",
                           f"Declara la variable como const {sin_cv(declarado)}& o sin '&'.",
                           "Ciclo for de rango", f"const {sin_cv(declarado)}&", str(declarado))
            elif self.compatible(sin_cv(declarado), elem, None, "init"):
                self.paso("Compatibilidad de tipos", tn, str(elem), str(declarado),
                          f"Cada elemento de '{txt}' ({elem}) se puede guardar en '{n.valor}' ({declarado}).")
            else:
                self.error(tn, f"Los elementos de '{txt}' son {elem} y no se pueden guardar en '{n.valor}' ({declarado})",
                           f"Declara la variable del ciclo como {sin_cv(elem)} o usa auto.",
                           "Ciclo for de rango", str(elem), str(declarado))
        x = self.pos_lexema(n, n.valor) if tn is None else self.pos_lexema(tn, n.valor)
        s = Simbolo(n.valor, "variable", t, x[0], x[1])
        self.registrar(s, x, None, "Variable del ciclo",
                       f"'{n.valor}' ({t}) toma, uno por uno, cada elemento de '{txt}'.")
        self.ciclos += 1
        self.cuerpo_en_ambito(cuerpo)
        self.ciclos -= 1
        self.cerrar(self.cierre(cuerpo) if cuerpo is not None and cuerpo.tipo == "Bloque" else (n.linea, n.columna, 3))

    def s_switch(self, n):
        cond = self.hijo(n, "Condición")
        x = cond.hijos[0] if cond is not None and cond.hijos else None
        t = self.expr(x) if x is not None else DESCONOCIDO
        k = self.cat(t)
        if k == "real":
            self.error(x, f"switch solo acepta valores enteros, char o enum, y '{self.texto(x)}' es {t}",
                       "Usa if / else if para comparar valores con decimales.", "Sentencia switch", "int, char o enum", str(t))
        elif k == "cadena" or es_texto_c(t):
            self.error(x, f"switch no funciona con texto, y '{self.texto(x)}' es {t}",
                       'Usa if / else if, por ejemplo: if (opcion == "a") ... else if (opcion == "b") ...',
                       "Sentencia switch", "int, char o enum", str(t))
        elif k not in ENTERAS | LIBRES | {"enum"}:
            self.error(x, f"switch necesita un valor entero, char o enum, y '{self.texto(x)}' es {t}",
                       "Usa una variable de tipo int, char o enum.", "Sentencia switch", "int, char o enum", str(t))
        elif x is not None:
            self.paso("Sentencia switch", x, "int, char o enum", str(t), f"El switch evalúa '{self.texto(x)}' ({t}).")
        self.switches += 1
        self.abrir("switch", "bloque", (n.linea, n.columna, 6))
        vistos, hay_default = {}, None
        for sec in n.hijos:
            if sec.tipo not in ("Case", "Default"):
                continue
            if sec.tipo == "Case":
                e = sec.hijos[0] if sec.hijos else None
                stmts = sec.hijos[1:]
                if e is not None:
                    te = self.expr(e)
                    v = self.valor_constante(e)
                    if self.cat(te) == "cadena" or es_texto_c(te):
                        self.error(e, f"Un case no puede tener texto ({self.texto(e)})",
                                   "switch solo compara números, caracteres ('a') o valores de enum.",
                                   "Etiqueta case", "constante entera", str(te))
                    elif self.cat(te) == "real":
                        self.error(e, f"Un case no puede tener un valor con decimales ({self.texto(e)})",
                                   "Usa valores enteros o caracteres en los case.", "Etiqueta case",
                                   "constante entera", str(te))
                    elif v is None and not self.es_constante_expr(e):
                        self.error(e, f"El valor de un case debe ser constante, y '{self.texto(e)}' es una variable",
                                   "No se pueden usar variables en un case; usa if / else if.",
                                   "Etiqueta case", "constante", self.texto(e))
                    elif v is not None:
                        if v in vistos:
                            self.error(e, f"El valor {self.texto(e)} ya se usó en otro case (línea {vistos[v]})",
                                       "Cada case debe tener un valor distinto.", "Etiqueta case",
                                       "valor nuevo", "valor repetido")
                        else:
                            vistos[v] = e.linea
                            self.paso("Etiqueta case", e, "constante", self.texto(e),
                                      f"case {self.texto(e)}: valor constante y sin repetir.")
            else:
                if hay_default is not None:
                    self.error((sec.linea, sec.columna, 7), f"El switch ya tiene un default (línea {hay_default})",
                               "Solo puede haber un default por switch.", "Sentencia switch", "un default", "dos")
                hay_default = sec.linea
                stmts = sec.hijos
            for st in stmts:
                self.seguro(self.sentencia, st)
        self.cerrar(self.cierre_switch(n))
        self.switches -= 1

    def cierre_switch(self, n):
        i = self.indice_tok.get((n.linea, n.columna))
        if i is None:
            return None
        for k in range(i, len(self.toks)):
            if self.toks[k].lexema == "{":
                t = self.toks[k]
                return self.cierre(type("N", (), {"linea": t.linea, "columna": t.columna}))
        return None

    def s_return(self, n):
        f = self.ctx.funcion if self.ctx is not None else None
        if f is None:
            return
        self.ctx.retornos += 1
        valor = n.hijos[0] if n.hijos else None
        es_void = f.categoria in ("constructor", "destructor") or self.cat(f.tipo) == "void"
        nombre = f.nombre
        x = (n.linea, n.columna, 6)
        if valor is None:
            if not es_void and self.cat(f.tipo) not in LIBRES:
                self.error(x, f"'{nombre}' debe devolver un valor de tipo {f.tipo}; 'return;' sin valor solo se usa en funciones void",
                           f"Escribe return seguido de un valor de tipo {f.tipo}.", "Sentencia return",
                           str(f.tipo), "return sin valor")
            else:
                self.paso("Sentencia return", x, "sin valor", "return;", f"'{nombre}' termina sin devolver valor.")
            return
        if es_void:
            t = self.tipo_arg(valor)
            if self.cat(t) not in {"void"} | LIBRES:
                que = "es void" if f.categoria not in ("constructor", "destructor") else f"es un {f.categoria}"
                self.error(valor, f"'{nombre}' {que} y no debe devolver ningún valor",
                           "Quita el valor del return, o cambia el tipo de la función si necesita devolver algo.",
                           "Sentencia return", "void", str(t))
            return
        if f.tipo.nombre == "auto":
            t = self.tipo_arg(valor)
            if t.nombre not in ("{}", "?"):
                f.tipo = sin_cv(decaer(t))
            return
        if valor.tipo == "ListaInicialización":
            self.revisar_lista(sin_cv(f.tipo), valor, f"valor de retorno de '{nombre}'")
            return
        t = self.expr(valor)
        self.compatible_o_error(sin_cv(f.tipo) if not f.tipo.punteros else replace(f.tipo, ref=False),
                                t, valor, "return", nombre, "Sentencia return")

    def s_break(self, n):
        if self.ciclos == 0 and self.switches == 0:
            self.error((n.linea, n.columna, 5), "'break' solo se puede usar dentro de un ciclo o de un switch",
                       "Quita el break; si querías terminar la función usa return.", "Sentencia break",
                       "ciclo o switch", "fuera de ellos")
        else:
            self.paso("Sentencia break", (n.linea, n.columna, 5), "ciclo o switch", "dentro",
                      "break está dentro de un ciclo o switch.")

    def s_continue(self, n):
        if self.ciclos == 0:
            self.error((n.linea, n.columna, 8), "'continue' solo se puede usar dentro de un ciclo",
                       "continue salta a la siguiente vuelta de un for, while o do-while; aquí no hay ninguno.",
                       "Sentencia continue", "ciclo", "fuera de un ciclo")

    def s_try(self, n):
        for h in n.hijos:
            if h.tipo == "Bloque":
                self.subsentencia(h, "try")
            elif h.tipo == "Catch":
                tn, b = self.hijo(h, "Tipo"), self.hijo(h, "Bloque")
                self.abrir("catch", "bloque", (h.linea, h.columna, 5))
                if tn is not None:
                    t = self.tipo_de(tn)
                    if h.valor and h.valor != "...":
                        x = self.pos_lexema(tn, h.valor)
                        self.registrar(Simbolo(h.valor, "parámetro", t, x[0], x[1]), x, None, "Parámetro de catch")
                for st in (b.hijos if b is not None else []):
                    self.seguro(self.sentencia, st)
                self.cerrar(self.cierre(b) if b is not None else (h.linea, h.columna, 5))

    def s_throw(self, n):
        if n.hijos:
            t = self.tipo_arg(n.hijos[0])
            if self.cat(t) == "void":
                self.error(n.hijos[0], "No se puede lanzar (throw) una expresión void",
                           "Lanza un valor u objeto, por ejemplo: throw runtime_error(\"mensaje\");",
                           "Sentencia throw", "valor", "void")

    # ═══════════════════════════ expresiones ═══════════════════════════
    def expr(self, n):
        if n is None:
            return DESCONOCIDO
        f = EXPRESIONES.get(n.tipo)
        if f is None:
            for h in n.hijos:
                self.expr(h)
            t = DESCONOCIDO
        else:
            t = f(self, n)
        self.tipos[n.id] = t
        return t

    def e_literal(self, n):
        t, v = n.tipo, (n.valor or "")
        if t == "LiteralEntero":
            suf = re.search(r"[uUlL]+$", v)
            s = suf.group(0).lower() if suf else ""
            return Tipo(("unsigned " if "u" in s else "") + ("long long" if "ll" in s else "long" if "l" in s else "int"))
        if t == "LiteralFlotante":
            return FLOAT if v[-1:] in "fF" else DOUBLE
        if t == "LiteralCadena":
            return CSTR
        if t == "LiteralCarácter":
            return Tipo("wchar_t") if v.startswith("L") else CHAR
        if t == "LiteralBooleano":
            return BOOL
        if t == "LiteralNulo":
            return NULO if v == "nullptr" else INT
        return DESCONOCIDO

    def no_declarado(self, n, nombre):
        clave = (self.ctx.funcion.nombre if self.ctx and self.ctx.funcion else self.pila[-1].nombre, nombre)
        if clave in self.reportados:
            return
        self.reportados.add(clave)
        otros = [s for s in self.tabla if s.nombre == nombre and s.categoria in ("variable", "parámetro")]
        if otros:
            o = otros[-1]
            sug = (f"'{nombre}' existe en el ámbito «{o.ambito}» (línea {o.linea}), pero no es visible aquí: "
                   f"una variable local solo existe dentro del bloque donde se declaró.")
        else:
            p = self.parecido(nombre)
            sug = (f"¿Quisiste decir '{p}'? " if p else "") + f"Declara '{nombre}' antes de usarla, por ejemplo: int {nombre} = 0;"
        self.error(n, f"El identificador '{nombre}' no está declarado en este ámbito", sug,
                   "Uso de identificador", f"'{nombre}' declarado", "no está en la tabla de símbolos")

    def e_ident(self, n):
        nombre = n.valor
        sims = self.buscar(nombre)
        if not sims:
            lib = self.biblioteca(nombre, n)
            if lib is not None:
                if lib.es_tipo:
                    self.error(n, f"'{nombre}' es un tipo de dato, no un valor",
                               f"Para crear una variable escribe: {nombre} variable;", "Uso de identificador",
                               "variable o función", f"tipo {nombre}")
                    return DESCONOCIDO
                self.paso("Uso de identificador", n, f"'{nombre}' declarado",
                          f"biblioteca: {lib.tipo}" if lib.tipo.nombre != "?" else "biblioteca estándar",
                          f"'{nombre}' pertenece a la biblioteca estándar"
                          + (f" ({lib.tipo})." if lib.tipo.nombre != "?" else "."))
                return lib.tipo
            if self.cabeceras_locales:
                return DESCONOCIDO
            self.no_declarado(n, nombre)
            return DESCONOCIDO
        s = sims[0]
        if s.categoria in ("biblioteca", "tipo de biblioteca"):
            if s.es_tipo:
                self.error(n, f"'{nombre}' es un tipo de dato, no un valor",
                           f"Para crear una variable escribe: {nombre} variable;", "Uso de identificador",
                           "variable o función", f"tipo {nombre}")
                return DESCONOCIDO
            return s.tipo
        if s.es_tipo:
            self.error(n, f"'{nombre}' es un tipo de dato ({s.categoria}), no una variable",
                       f"Para crear un objeto escribe: {nombre} variable; o {nombre}(...).",
                       "Uso de identificador", "variable o función", f"{s.categoria} '{nombre}'")
            return DESCONOCIDO
        if s.categoria in ("función", "método"):
            self.paso("Uso de identificador", n, f"'{nombre}' declarado", s.categoria,
                      f"'{nombre}' es {art(s.categoria)} (línea {s.linea}).")
            return FUNCION
        t = s.tipo
        if s.clase and s.acceso != "public" and "::" in nombre:
            self.verificar_acceso(s, n, self.clases.get(s.clase))
        if s.categoria == "atributo" and s.clase and not s.estatico and self.ctx is not None and "::" not in nombre:
            if self.ctx.estatico:
                self.error(n, f"El método static '{self.ctx.funcion.nombre}' no puede usar el atributo '{nombre}'",
                           "Un método static no pertenece a ningún objeto; quita static o recibe el objeto como parámetro.",
                           "Uso de identificador", "atributo static", f"atributo '{nombre}'")
            if self.ctx.const:
                t = replace(t, const=True)
        self.paso("Uso de identificador", n, f"'{nombre}' declarado", f"{s.categoria} {t} (lín. {s.linea})",
                  f"'{nombre}' está en la tabla de símbolos: {s.categoria} de tipo {t}, "
                  f"línea {s.linea}, ámbito {s.ambito}.")
        return t

    def es_lvalue(self, x):
        t = x.tipo
        if t == "Identificador":
            sims = self.buscar(x.valor)
            if not sims:
                return True
            s = sims[0]
            return not s.es_tipo and s.categoria in ("variable", "parámetro", "atributo", "biblioteca")
        if t in ("Índice", "Desreferencia", "AccesoPuntero", "AccesoMiembro", "Asignación"):
            return True
        if t == "Unaria" and x.valor in ("++", "--"):
            return True
        if t == "Llamada":
            ty = self.tipos.get(x.id)
            return ty is None or ty.ref or self.cat(ty) in LIBRES
        if t == "Ternario" and len(x.hijos) == 3:
            return self.es_lvalue(x.hijos[1]) and self.es_lvalue(x.hijos[2])
        return False

    def motivo_const(self, izq, tl):
        if izq.tipo == "Identificador":
            sims = self.buscar(izq.valor)
            s = sims[0] if sims else None
            if (s is not None and s.categoria == "atributo" and s.clase and not s.estatico
                    and self.ctx is not None and self.ctx.const and self.ctx.funcion is not None
                    and not s.tipo.const):
                return (f"No se puede modificar el atributo '{s.nombre}' dentro del método const '{self.ctx.funcion.nombre}'",
                        f"Quita const del método si necesita modificar atributos, o no modifiques '{s.nombre}' aquí.")
            if tl.const:
                return (f"No se puede modificar '{izq.valor}' porque es constante (const)",
                        "Si necesitas cambiar su valor, declárala sin const.")
            return None
        if tl.const:
            return (f"No se puede modificar '{self.texto(izq)}' porque es de solo lectura (const)",
                    "El objeto, arreglo o puntero del que forma parte es constante; quita const si necesitas modificarlo.")
        return None

    def e_asignacion(self, n):
        op = n.valor
        izq = n.hijos[0] if n.hijos else None
        der = n.hijos[1] if len(n.hijos) > 1 else None
        tl = self.expr(izq)
        es_lista = der is not None and der.tipo == "ListaInicialización"
        tr = LISTA if es_lista else self.expr(der)
        destino = self.texto(izq)
        if not self.es_lvalue(izq):
            sims = self.buscar(izq.valor) if izq.tipo == "Identificador" else []
            s = sims[0] if sims else None
            if s is not None and s.categoria in ("macro", "enumerador"):
                msg, sug = (f"'{izq.valor}' es una constante ({s.categoria}) y no se puede modificar",
                            "Usa una variable si necesitas cambiar el valor.")
            elif s is not None and s.categoria in ("función", "método"):
                msg, sug = (f"'{izq.valor}' es una función y no se le puede asignar un valor",
                            "Si querías guardar su resultado, usa una variable: int r = funcion(...);")
            else:
                msg, sug = (f"El lado izquierdo de '{op}' debe ser una variable, y '{destino}' no lo es",
                            "Solo se puede asignar a variables, elementos de un arreglo o atributos. "
                            "Si querías comparar usa '=='.")
            self.error(izq, msg, sug, "Asignación", "variable", destino)
            if es_lista:
                self.tipo_arg(der)
            return tl
        motivo = self.motivo_const(izq, tl)
        if motivo:
            self.error(izq, motivo[0], motivo[1], "Asignación", "variable modificable", f"const {sin_cv(tl)}")
            if es_lista:
                self.tipo_arg(der)
            return tl
        c = self.cat(tl)
        if op == "=":
            if c == "arreglo":
                self.error(n, f"No se puede asignar un arreglo completo con '='",
                           "Copia los elementos uno por uno con un ciclo, o usa vector, que sí se puede asignar.",
                           "Asignación", "elemento del arreglo", str(tl))
                if es_lista:
                    self.tipo_arg(der)
            elif es_lista:
                self.revisar_lista(sin_cv(tl), der, destino)
            else:
                self.compatible_o_error(sin_cv(tl) if not tl.punteros else replace(tl, ref=False, const=False),
                                        tr, der, "asig", destino, "Asignación")
        elif es_lista:
            self.tipo_arg(der)
        elif c == "cadena" and op == "+=" and (self.cat(tr) == "cadena" or es_texto_c(tr) or es_char(tr)):
            self.paso("Asignación compuesta", n, "string += texto", f"{tl} += {tr}",
                      f"Se agrega texto al final de '{destino}'.", exacto=True)
        else:
            self.operar(op[:-1], tl, tr, n, izq, der)
        return tl

    def operador_de(self, op, ti, td=None):
        """Si una clase sobrecarga el operador, devuelve el tipo de retorno (None si no existe)."""
        for t in (ti, td):
            if t is not None and self.cat(t) == "clase":
                ms = self.miembro(self.info_clase(t), "operator" + op)
                if ms:
                    return ms[0].tipo
        fs = self.ops_globales.get(op)
        if fs and any(t is not None and self.cat(t) in ("clase", "enum", "enum_simple", "contenedor") for t in (ti, td)):
            return fs[0].tipo
        return None

    def e_binaria(self, n):
        izq = n.hijos[0] if n.hijos else None
        der = n.hijos[1] if len(n.hijos) > 1 else None
        return self.operar(n.valor, self.expr(izq), self.expr(der), n, izq, der)

    def operar(self, op, ti, td, n, izq, der):
        a, b = self.cat(ti), self.cat(td)
        x_op = (n.linea, n.columna, len(n.valor or op))
        desc = f"{ti} {op} {td}"
        for lado, k in ((izq, a), (der, b)):
            if k == "void":
                self.error(lado, f"'{self.texto(lado)}' no devuelve ningún valor (es void) y no se puede usar en una operación",
                           "Usa una función que devuelva un valor (con return) o quita esa parte de la operación.",
                           "Operación", "valor", "void")
                return DESCONOCIDO
            if k == "funcion":
                self.error(lado, f"'{self.texto(lado)}' es una función: para usar su resultado faltan los paréntesis",
                           f"Escribe {self.texto(lado)}(...) para llamarla.", "Operación", "valor", "función")
                return DESCONOCIDO
        if op in ("<<", ">>") and a == "flujo":
            return self.op_flujo(op, ti, td, n, izq, der)
        if a in LIBRES | {"lista"} or b in LIBRES | {"lista"}:
            return BOOL if op in COMPARACIONES | LOGICOS else DESCONOCIDO
        if op in ("+", "-", "*", "/"):
            if a in NUMERICAS and b in NUMERICAS:
                if op == "/" and der is not None and self.valor_constante(der) == 0:
                    self.error(der, "División entre cero: el divisor siempre vale 0",
                               "Revisa la operación o valida que el divisor no sea cero antes de dividir.",
                               "Operación aritmética", "divisor distinto de 0", "0")
                    return self.promover(ti, td)
                r = self.promover(ti, td)
                self.paso("Operación aritmética", x_op, "operandos numéricos", f"{desc} → {r}",
                          f"'{op}' entre {sin_cv(ti)} y {sin_cv(td)} da un resultado {r}.")
                return r
            if op == "+":
                if ((a == "cadena" and (b == "cadena" or es_texto_c(td) or es_char(td)))
                        or (b == "cadena" and (es_texto_c(ti) or es_char(ti)))):
                    self.paso("Concatenación", x_op, "string + texto", f"{desc} → string",
                              "'+' une los dos textos en un string.")
                    return STRING
                if es_texto_c(ti) and es_texto_c(td):
                    self.error(n, "No se pueden unir dos textos entre comillas con '+'",
                               'Convierte uno de ellos a string: string("Hola ") + "mundo", o escríbelos juntos en un solo texto.',
                               "Concatenación", "string + texto", desc)
                    return STRING
            if op in ("+", "-") and a in PUNTEROS and b in ENTERAS:
                return decaer(ti)
            if op == "+" and b in PUNTEROS and a in ENTERAS:
                return decaer(td)
            if op == "-" and a in PUNTEROS and b in PUNTEROS:
                return Tipo("ptrdiff_t")
            r = self.operador_de(op, ti, td)
            if r is not None:
                return r
            if (a == "cadena" and b in NUMERICAS) or (b == "cadena" and a in NUMERICAS):
                if op == "+":
                    msg, sug = (f"No se puede sumar {sin_cv(ti)} con {sin_cv(td)}",
                                "Para unir texto con un número conviértelo primero: to_string(numero).")
                else:
                    msg, sug = (f"El operador '{op}' no se puede usar con texto (string)",
                                "Los operadores -, * y / solo funcionan con números; si el texto contiene "
                                "un número conviértelo con stoi() o stod().")
            elif "cadena" in (a, b):
                msg, sug = (f"El operador '{op}' no se puede usar entre {ti} y {td}",
                            "Con string solo se puede usar '+' para unir textos.")
            else:
                msg, sug = (f"El operador '{op}' no se puede aplicar a {ti} y {td}",
                            "Los operadores aritméticos necesitan números (int, double, ...).")
            self.error(n, msg, sug, "Operación aritmética", "operandos numéricos", desc)
            return DESCONOCIDO
        if op == "%":
            if a in ENTERAS and b in ENTERAS:
                if der is not None and self.valor_constante(der) == 0:
                    self.error(der, "Residuo entre cero: el divisor de '%' siempre vale 0",
                               "El divisor de '%' no puede ser cero.", "Operación aritmética", "divisor distinto de 0", "0")
                r = self.promover(ti, td)
                self.paso("Operación aritmética", x_op, "operandos enteros", f"{desc} → {r}",
                          f"'%' (residuo) entre enteros da un resultado {r}.")
                return r
            r = self.operador_de(op, ti, td)
            if r is not None:
                return r
            if a in NUMERICAS and b in NUMERICAS:
                real = sin_cv(ti) if a == "real" else sin_cv(td)
                self.error(n, f"El operador '%' solo funciona con enteros, y aquí se usa con {real}",
                           "Para el residuo de números con decimales usa fmod(a, b) de <cmath>, o convierte los valores a int.",
                           "Operación aritmética", "int % int", desc)
            else:
                self.error(n, f"El operador '%' no se puede aplicar a {ti} y {td}",
                           "El residuo (%) solo se calcula entre números enteros.", "Operación aritmética",
                           "int % int", desc)
            return DESCONOCIDO
        if op in COMPARACIONES:
            if self.comparables(ti, td, izq, der):
                self.paso("Comparación", x_op, "tipos comparables", f"{desc} → bool",
                          f"Se pueden comparar {sin_cv(ti)} y {sin_cv(td)} con '{op}'; el resultado es bool.")
                return BOOL
            if self.operador_de(op, ti, td) is not None:
                return BOOL
            if es_char(ti) and td == CSTR or es_char(td) and ti == CSTR:
                sug = "Para comparar un char usa comillas simples: 'a' (las comillas dobles son para texto)."
            elif "cadena" in (a, b) and (a in NUMERICAS or b in NUMERICAS):
                sug = 'Compara texto con texto ("5") o convierte primero con stoi() o to_string().'
            elif "clase" in (a, b):
                sug = f"La clase no define el operador '{op}'; compara sus atributos o define operator{op}."
            else:
                sug = "Solo se pueden comparar valores de tipos compatibles (números con números, texto con texto...)."
            self.error(n, f"No se puede comparar {ti} con {td} usando '{op}'", sug, "Comparación",
                       "tipos comparables", desc)
            return BOOL
        if op in LOGICOS:
            for t, lado in ((ti, izq), (td, der)):
                if not self.a_bool(t):
                    self.error(lado, f"El operador '{op}' necesita valores verdadero/falso, pero '{self.texto(lado)}' es {t}",
                               'Usa una comparación, por ejemplo: (x > 0) && (nombre != "").',
                               "Operación lógica", "bool", str(t))
            return BOOL
        if op in ("&", "|", "^", "<<", ">>", "bitand", "bitor", "xor"):
            if a in ENTERAS and b in ENTERAS:
                return self.promover(ti, td)
            r = self.operador_de(op, ti, td)
            if r is not None:
                return r
            sug = ("Si querías imprimir o leer, el lado izquierdo debe ser cout o cin." if op in ("<<", ">>")
                   else "Para condiciones usa && y ||; los operadores &, | y ^ trabajan bit a bit con enteros.")
            self.error(n, f"El operador '{op}' solo se aplica a números enteros; aquí se usa con {ti} y {td}",
                       sug, "Operación de bits", "enteros", desc)
            return DESCONOCIDO
        return DESCONOCIDO

    def comparables(self, ti, td, izq, der):
        a, b = self.cat(ti), self.cat(td)
        if a in NUMERICAS and b in NUMERICAS:
            return True
        if a == "cadena" and (b == "cadena" or es_texto_c(td)):
            return True
        if b == "cadena" and es_texto_c(ti):
            return True
        if a in PUNTEROS and (b in PUNTEROS or b == "nulo" or self.es_cero_literal(der)):
            return True
        if b in PUNTEROS and (a == "nulo" or self.es_cero_literal(izq)):
            return True
        if a == b and a in ("nulo", "enum", "contenedor") and (a == "nulo" or base(ti.nombre) == base(td.nombre)):
            return True
        return False

    def raiz_flujo(self, x):
        while x is not None and x.tipo == "Binaria" and x.valor in ("<<", ">>") and x.hijos:
            x = x.hijos[0]
        return self.texto(x) if x is not None else "flujo"

    def op_flujo(self, op, ti, td, n, izq, der):
        b = base(ti.nombre)
        salida = b in FLUJOS_SALIDA | FLUJOS_AMBOS
        entrada = b in FLUJOS_ENTRADA | FLUJOS_AMBOS
        nf = self.raiz_flujo(izq)
        x_op = (n.linea, n.columna, 2)
        if op == "<<" and not salida:
            self.error(x_op, f"Con '{nf}' se lee usando '>>', no '<<'",
                       f"Escribe {nf} >> variable; para leer un dato.", "Entrada/salida", "'>>'", "'<<'")
            return ti
        if op == ">>" and not entrada:
            self.error(x_op, f"Con '{nf}' se muestra usando '<<', no '>>'",
                       f"Escribe {nf} << valor; para mostrar un dato.", "Entrada/salida", "'<<'", "'>>'")
            return ti
        c = self.cat(td)
        if c in ("clase", "contenedor") and self.operador_de(op, ti, td) is None:
            if op == "<<":
                sug = ("Recorre el contenedor con un for y muestra cada elemento." if c == "contenedor"
                       else "Muestra sus atributos uno por uno (por ejemplo obj.nombre) o define operator<< para ese tipo.")
                self.error(der, f"'{nf}' no sabe mostrar un valor de tipo {td}", sug, "Salida de datos",
                           "valor imprimible", str(td))
            else:
                self.error(der, f"'{nf}' no sabe leer directamente un valor de tipo {td}",
                           "Lee sus datos uno por uno en variables simples.", "Entrada de datos",
                           "variable simple", str(td))
            return ti
        if op == "<<":
            desc = f" ({td})" if c not in LIBRES else ""
            self.paso("Salida de datos", der, "valor imprimible", str(td) if desc else "manipulador / valor",
                      f"Se envía {self.texto(der)}{desc} a {nf}.")
            return ti
        if not self.es_lvalue(der):
            self.error(der, f"'{nf} >>' necesita una variable donde guardar el dato, y '{self.texto(der)}' no lo es",
                       f"Escribe el nombre de una variable: {nf} >> variable;", "Entrada de datos", "variable",
                       self.texto(der))
        elif td.const:
            self.error(der, f"No se puede leer en '{self.texto(der)}' porque es constante",
                       "Lee el dato en una variable que no sea const.", "Entrada de datos", "variable modificable",
                       str(td))
        else:
            self.paso("Entrada de datos", der, "variable", str(td),
                      f"El dato leído de {nf} se guarda en '{self.texto(der)}' ({td}).")
        return ti

    def e_ternario(self, n):
        hs = (n.hijos + [None, None, None])[:3]
        cond, a, b = hs
        tc = self.expr(cond)
        if not self.a_bool(tc):
            self.error(cond, f"La condición de '?:' debe ser verdadero o falso, pero '{self.texto(cond)}' es {tc}",
                       "Usa una comparación, por ejemplo: (x > 0) ? a : b.", "Expresión condicional", "bool", str(tc))
        ta, tb = self.tipo_arg(a) if a is not None else DESCONOCIDO, self.tipo_arg(b) if b is not None else DESCONOCIDO
        ca, cb = self.cat(ta), self.cat(tb)
        if ca in LIBRES | {"lista"}:
            return tb
        if cb in LIBRES | {"lista"}:
            return ta
        if ca in NUMERICAS and cb in NUMERICAS:
            return self.promover(ta, tb)
        if str(sin_cv(decaer(ta))) == str(sin_cv(decaer(tb))):
            return sin_cv(ta)
        if ca in PUNTEROS and (cb == "nulo" or self.es_cero_literal(b)):
            return decaer(ta)
        if cb in PUNTEROS and (ca == "nulo" or self.es_cero_literal(a)):
            return decaer(tb)
        if (ca == "cadena" and es_texto_c(tb)) or (cb == "cadena" and es_texto_c(ta)):
            return STRING
        if es_texto_c(ta) and es_texto_c(tb):
            return CSTR
        if ca == cb == "clase" and (self.hereda(ta.nombre, tb.nombre) or self.hereda(tb.nombre, ta.nombre)):
            return tb if self.hereda(ta.nombre, tb.nombre) else ta
        if ca == cb == "void":
            return VOID
        self.error(n, f"Las dos opciones de '?:' deben ser del mismo tipo, pero son {ta} y {tb}",
                   "Haz que ambas opciones den el mismo tipo de dato (por ejemplo, las dos string o las dos int).",
                   "Expresión condicional", str(ta), str(tb), exacto=True, largo=1)
        return DESCONOCIDO

    def incremento(self, op, x, t, n):
        c = self.cat(t)
        if c not in NUMERICAS | LIBRES | {"puntero"} or c == "enum_simple":
            if c == "clase" and self.operador_de(op, t) is not None:
                return t
            self.error(x, f"'{op}' solo se aplica a variables numéricas o punteros, y '{self.texto(x)}' es {t}",
                       "Para cambiar el valor usa una asignación, por ejemplo: x = x + 1;",
                       "Incremento/decremento", "número", str(t))
            return t
        if not self.es_lvalue(x):
            self.error(x, f"'{op}' necesita una variable, y '{self.texto(x)}' no lo es",
                       "Por ejemplo: contador++;  (no 5++ ni (a + b)++).", "Incremento/decremento",
                       "variable", self.texto(x))
        else:
            motivo = self.motivo_const(x, t)
            if motivo:
                self.error(x, motivo[0], motivo[1], "Incremento/decremento", "variable modificable", f"const {sin_cv(t)}")
        return sin_cv(t)

    def e_unaria(self, n):
        op = n.valor
        x = n.hijos[0] if n.hijos else None
        t = self.expr(x)
        c = self.cat(t)
        txt = self.texto(x)
        if c == "void":
            self.error(x, f"'{txt}' no devuelve ningún valor (es void)", "Usa una expresión que devuelva un valor.",
                       "Operación unaria", "valor", "void")
            return DESCONOCIDO
        if op in ("!", "not"):
            if not self.a_bool(t):
                self.error(x, f"El operador '!' necesita un valor verdadero/falso, pero '{txt}' es {t}",
                           "Usa una comparación, por ejemplo: !(x > 0) o !texto.empty().",
                           "Operación lógica", "bool", str(t))
            return BOOL
        if op in ("-", "+"):
            if c in NUMERICAS:
                return sin_cv(t) if c == "real" else self.promover(t, INT)
            if c in LIBRES:
                return DESCONOCIDO
            r = self.operador_de(op, t)
            if r is not None:
                return r
            self.error(n, f"El signo '{op}' solo se aplica a números, y '{txt}' es {t}",
                       "Usa el signo con valores numéricos.", "Operación unaria", "número", str(t))
            return DESCONOCIDO
        if op in ("~", "compl"):
            if c in ENTERAS:
                return self.promover(t, INT)
            if c in LIBRES:
                return DESCONOCIDO
            self.error(n, f"El operador '~' solo se aplica a enteros, y '{txt}' es {t}",
                       "'~' invierte los bits de un entero; para negar una condición usa '!'.",
                       "Operación de bits", "entero", str(t))
            return DESCONOCIDO
        if op in ("++", "--"):
            return self.incremento(op, x, t, n)
        return DESCONOCIDO

    def e_postfijo(self, n):
        x = n.hijos[0] if n.hijos else None
        return self.incremento(n.valor, x, self.expr(x), n)

    def e_desref(self, n):
        x = n.hijos[0] if n.hijos else None
        t = self.expr(x)
        c = self.cat(t)
        if c in PUNTEROS:
            if t.nombre == "void" and niveles(t) == 1:
                self.error(n, "No se puede usar '*' con un puntero void*",
                           "Conviértelo primero al tipo correcto, por ejemplo: *(int*) p o *static_cast<int*>(p).",
                           "Desreferencia", "puntero con tipo", "void*")
                return DESCONOCIDO
            return elemento(t)
        if c in LIBRES:
            return DESCONOCIDO
        if c == "clase" and self.operador_de("*", t) is not None:
            return DESCONOCIDO
        self.error(n, f"No se puede usar '*' con '{self.texto(x)}' porque no es un puntero (es {t})",
                   "'*' obtiene el valor al que apunta un puntero, por ejemplo: int* p = &x; cout << *p;",
                   "Desreferencia", "puntero", str(t))
        return DESCONOCIDO

    def e_direccion(self, n):
        x = n.hijos[0] if n.hijos else None
        t = self.expr(x)
        c = self.cat(t)
        if c in {"funcion"} | LIBRES:
            return DESCONOCIDO
        if not self.es_lvalue(x):
            self.error(n, f"Solo se puede obtener la dirección (&) de una variable, y '{self.texto(x)}' no lo es",
                       "Por ejemplo: int* p = &x;", "Dirección de memoria", "variable", self.texto(x))
            return DESCONOCIDO
        if t.dims:
            return DESCONOCIDO
        if t.punteros:
            return Tipo(t.nombre, t.punteros + 1, const_base=t.const_base)
        return Tipo(t.nombre, 1, const_base=t.const)

    def e_sizeof(self, n):
        h = n.hijos[0] if n.hijos else None
        if h is not None:
            if h.tipo == "Tipo":
                # el sintáctico guarda sizeof(variable) como si 'variable' fuera un tipo
                t = texto_a_tipo(h.valor)
                sims = self.buscar(t.nombre) if not t.punteros and " " not in t.nombre else []
                if sims and not any(s.es_tipo for s in sims):
                    self.paso("Uso de identificador", h, f"'{t.nombre}' declarado", str(sims[0].tipo),
                              f"sizeof mide el tamaño en bytes de '{t.nombre}' ({sims[0].tipo}).")
                else:
                    self.tipo_de(h)
            else:
                self.expr(h)
        return SIZE_T

    def e_delete(self, n):
        x = n.hijos[0] if n.hijos else None
        t = self.expr(x)
        c = self.cat(t)
        if c in {"puntero", "nulo"} | LIBRES:
            self.paso("Liberación de memoria", n, "puntero", str(t), f"Se libera la memoria a la que apunta '{self.texto(x)}'.")
        else:
            self.error(n, f"delete solo se usa con punteros creados con new, y '{self.texto(x)}' es {t}",
                       "Las variables normales y los arreglos declarados con [] se liberan solos al terminar su bloque.",
                       "Liberación de memoria", "puntero", str(t))
        return VOID

    def revisar_conversion(self, dest, src, n, como):
        cd, cs = self.cat(dest), self.cat(src)
        if cd in LIBRES or cs in LIBRES:
            return
        if cs == "void":
            self.error(n, f"No se puede convertir a {dest} algo que no devuelve valor (void)",
                       "Convierte una expresión que sí devuelva un valor.", "Conversión de tipo", "valor", "void")
        elif cd in NUMERICAS and (cs == "cadena" or es_texto_c(src)):
            self.error(n, f"No se puede convertir {src} a {dest} con un cast",
                       "Para convertir texto a número usa stoi() (enteros) o stod() (decimales).",
                       "Conversión de tipo", str(dest), str(src))
        elif cd == "cadena" and cs in NUMERICAS:
            self.error(n, f"No se puede convertir {src} a string con un cast",
                       "Para convertir un número a texto usa to_string(valor).", "Conversión de tipo",
                       "string", str(src))
        elif cd in NUMERICAS and cs in ("contenedor", "clase") and self.operador_de(" " + dest.nombre, src) is None:
            self.error(n, f"No se puede convertir un valor {src} a {dest}",
                       "Convierte uno de sus datos (atributo o elemento), no el objeto completo.",
                       "Conversión de tipo", str(dest), str(src))
        elif como == "static_cast" and ((cd == "puntero" and cs in NUMERICAS) or (cd in NUMERICAS and cs in PUNTEROS)):
            self.error(n, f"static_cast no convierte entre punteros y números ({src} → {dest})",
                       "Normalmente esto indica un error; si de verdad lo necesitas usa reinterpret_cast.",
                       "Conversión de tipo", str(dest), str(src))
        else:
            self.paso("Conversión de tipo", n, str(dest), str(src), f"El valor {src} se convierte a {dest}.")

    def e_conversion(self, n):
        if n.valor in CASTS:
            tn = n.hijos[0] if n.hijos and n.hijos[0].tipo == "Tipo" else None
            x = n.hijos[1] if len(n.hijos) > 1 else None
            dest = self.tipo_de(tn) if tn is not None else DESCONOCIDO
            como = n.valor
        else:
            x = n.hijos[0] if n.hijos else None
            dest = self.resolver(texto_a_tipo(n.valor), n)
            como = "conversión"
        src = self.expr(x)
        self.revisar_conversion(dest, src, n, como)
        return dest

    def e_conv_funcional(self, n):
        dest = self.resolver(texto_a_tipo(n.valor), n)
        h = n.hijos[0] if n.hijos else None
        args = h.hijos if h is not None else []
        targs = [self.tipo_arg(a) for a in args]
        if len(args) == 1 and targs[0].nombre != "{}":
            if h.tipo == "ListaInicialización" and self.cat(dest) in ("entero", "bool") and self.cat(targs[0]) == "real":
                self.error(args[0], f"Conversión con pérdida: no se puede convertir {targs[0]} a {dest} usando llaves",
                           f"Usa paréntesis: {dest}(valor), o static_cast<{dest}>(valor).",
                           "Conversión de tipo", str(dest), str(targs[0]))
            else:
                self.revisar_conversion(dest, targs[0], n, "conversión")
        return dest

    def e_new(self, n):
        tn = self.hijo(n, "Tipo")
        t = self.resolver(texto_a_tipo(n.valor), tn) if tn is not None else DESCONOCIDO
        resto = [h for h in n.hijos if h is not tn]
        resultado = Tipo(t.nombre, t.punteros + 1, const_base=t.const if not t.punteros else t.const_base)
        if t.nombre == "?":
            for h in resto:
                self.tipo_arg(h) if h.tipo != "Argumentos" else [self.tipo_arg(a) for a in h.hijos]
            return DESCONOCIDO
        if n.tipo == "NewArreglo":
            tam = resto[0] if resto else None
            if tam is not None:
                tt = self.expr(tam)
                v = self.valor_constante(tam)
                if self.cat(tt) not in ENTERAS | LIBRES:
                    self.error(tam, f"El tamaño en new[] debe ser un número entero; se encontró {tt}",
                               "Usa un int para el tamaño, por ejemplo: new int[n];", "Expresión new", "entero", str(tt))
                elif isinstance(v, int) and v < 0:
                    self.error(tam, f"El tamaño en new[] no puede ser negativo ({v})", "Usa un tamaño mayor o igual a cero.",
                               "Expresión new", "tamaño ≥ 0", str(v))
            for h in resto[1:]:
                self.tipo_arg(h)
            if self.cat(t) == "clase" and not t.punteros:
                info = self.info_clase(t)
                if info is not None and info.puras:
                    self.construir(info, [], [], n)
            return resultado
        init = resto[0] if resto else None
        if self.cat(t) == "clase" and not t.punteros:
            info = self.info_clase(t)
            if init is None:
                self.construir(info, [], [], n)
            elif init.tipo == "Argumentos":
                self.construir(info, init.hijos, [self.tipo_arg(a) for a in init.hijos], n)
            else:
                self.revisar_lista(t, init, f"new {t}")
        elif init is not None:
            if init.tipo == "Argumentos":
                args = init.hijos
                targs = [self.tipo_arg(a) for a in args]
                if len(args) == 1:
                    self.compatible_o_error(sin_cv(t), targs[0], args[0], "init", f"new {t}", "Expresión new")
                elif len(args) > 1 and self.cat(t) not in {"contenedor", "cadena"} | LIBRES:
                    self.error(args[1], f"Demasiados valores para new {t}; solo puede recibir uno",
                               f"Deja un solo valor: new {t}({self.texto(args[0])}).", "Expresión new",
                               "1 valor", f"{len(args)} valores")
            else:
                self.revisar_lista(sin_cv(t), init, f"new {t}")
        self.paso("Expresión new", n, "tipo declarado", str(resultado), f"new reserva memoria y devuelve un {resultado}.")
        return resultado

    def e_this(self, n):
        if self.ctx is None or self.ctx.clase is None:
            self.error(n, "'this' solo se puede usar dentro de los métodos de una clase",
                       "Fuera de una clase no hay un objeto actual al que 'this' pueda apuntar.",
                       "Uso de this", "método de una clase", "función libre")
            return DESCONOCIDO
        if self.ctx.estatico:
            self.error(n, f"'this' no existe dentro del método static '{self.ctx.funcion.nombre}'",
                       "Un método static no pertenece a ningún objeto; quita static si necesitas this.",
                       "Uso de this", "método normal", "método static")
            return DESCONOCIDO
        return Tipo(self.ctx.clase.nombre, 1, const_base=self.ctx.const)

    def e_lista(self, n):
        for e in n.hijos:
            self.tipo_arg(e)
        return LISTA

    def e_indice(self, n):
        b = n.hijos[0] if n.hijos else None
        i = n.hijos[1] if len(n.hijos) > 1 else None
        tb, ti = self.expr(b), self.expr(i)
        cb, ci = self.cat(tb), self.cat(ti)
        nombre = self.texto(b)

        def revisar_indice():
            if ci not in ENTERAS | LIBRES:
                self.error(i, f"El índice de '{nombre}' debe ser un número entero, pero '{self.texto(i)}' es {ti}",
                           "Usa un int como índice; si es un double conviértelo con (int) o static_cast<int>().",
                           "Índice", "entero", str(ti))
                return False
            return True

        if cb in PUNTEROS:
            if revisar_indice() and cb == "arreglo" and tb.dims and tb.dims[0]:
                v = self.valor_constante(i)
                d = tb.dims[0]
                if isinstance(v, int) and (v < 0 or v >= d):
                    self.error(i, f"El índice {v} está fuera del arreglo '{nombre}', que tiene {plural(d, 'elemento')} (índices 0 a {d - 1})",
                               f"Usa un índice entre 0 y {d - 1}.", "Índice de arreglo", f"0 a {d - 1}", str(v))
                else:
                    self.paso("Índice de arreglo", n, "índice entero", str(ti),
                              f"Se accede a un elemento de '{nombre}' ({elemento(tb)}).")
            return elemento(tb)
        if cb == "cadena":
            revisar_indice()
            return Tipo("char", const=tb.const)
        if cb == "contenedor":
            bb = base(tb.nombre)
            if bb in ("vector", "deque", "array"):
                revisar_indice()
                e = self.elemento_contenedor(tb)
                return replace(e, const=tb.const or e.const, ref=False)
            if bb in ("map", "unordered_map"):
                if tb.const:
                    self.error(b, f"No se puede usar [ ] con '{nombre}' porque es un map constante",
                               "Usa .at(clave) para leer de un map const.", "Índice", "map no const", str(tb))
                k = self.elemento_contenedor(tb, 0)
                if not self.compatible(k, ti, i, "param"):
                    self.error(i, f"Las claves de '{nombre}' son {k}, pero se usa {ti}",
                               f"Usa una clave de tipo {k}.", "Índice", str(k), str(ti))
                return self.elemento_contenedor(tb, 1)
            sug = {"list": "Recórrela con un for de rango o con iteradores.",
                   "set": "Recórrelo con un for de rango o usa find().",
                   "stack": "Usa top() para ver el elemento de arriba.",
                   "queue": "Usa front() y back()."}.get(bb, "Usa sus métodos o recórrelo con un for de rango.")
            self.error(b, f"{bb} no permite acceder a sus elementos con [ ]", sug, "Índice",
                       "vector, arreglo o string", str(tb))
            return DESCONOCIDO
        if cb in LIBRES:
            return DESCONOCIDO
        if cb == "clase":
            r = self.operador_de("[]", tb, ti)
            if r is not None:
                return r
        self.error(b, f"No se puede usar [ ] con '{nombre}' porque es {tb}",
                   "Los corchetes solo se usan con arreglos, punteros, string y vector.", "Índice",
                   "arreglo, string o vector", str(tb))
        return DESCONOCIDO

    def verificar_acceso(self, m, x, info):
        if m.acceso == "public" or info is None:
            return
        actual = self.ctx.clase if self.ctx is not None else None
        if actual is not None and (actual.nombre == m.clase
                                   or (m.acceso == "protected" and self.hereda(actual.nombre, m.clase))):
            return
        dueno = self.clases.get(m.clase)
        if dueno is not None and self.ctx is not None and self.ctx.funcion is not None \
                and self.ctx.funcion.nombre in dueno.amigos:
            return
        que = {"atributo": "El atributo", "método": "El método"}.get(m.categoria, f"El {m.categoria}")
        self.error(x, f"{que} '{m.nombre}' es {m.acceso} en '{m.clase}' y no se puede usar desde aquí",
                   f"Usa un método público de '{m.clase}' (por ejemplo un get o set) o mueve '{m.nombre}' a la sección public.",
                   "Control de acceso", "miembro public", f"miembro {m.acceso}", exacto=True)

    def objeto_de(self, acc):
        """Tipo del objeto en obj.miembro / ptr->miembro (revisa que se use '.' o '->' correctamente)."""
        obj = acc.hijos[0] if acc.hijos else None
        to = self.expr(obj)
        c = self.cat(to)
        txt, m = self.texto(obj), acc.valor
        if acc.tipo == "AccesoPuntero":
            if c == "puntero":
                return elemento(to)
            if c in LIBRES or (c == "clase" and self.operador_de("->", to) is not None):
                return DESCONOCIDO
            self.error((acc.linea, acc.columna, len(m)), f"'->' se usa con punteros, pero '{txt}' es {to}",
                       f"Usa punto: {txt}.{m}", "Acceso a miembro", "puntero", str(to))
            return elemento(to) if c == "arreglo" else to
        if c == "puntero":
            self.error((acc.linea, acc.columna, len(m)), f"'{txt}' es un puntero ({to}); para usar sus miembros se escribe '->'",
                       f"Escribe {txt}->{m} (o (*{txt}).{m}).", "Acceso a miembro", "objeto", str(to))
            return elemento(to)
        if c == "arreglo":
            self.error((acc.linea, acc.columna, len(m)), f"'{txt}' es un arreglo; primero elige un elemento con [ ]",
                       f"Por ejemplo: {txt}[0].{m}", "Acceso a miembro", "objeto", str(to))
            return elemento(to)
        return to

    def e_acceso(self, n):
        tobj = self.objeto_de(n)
        nombre = n.valor
        c = self.cat(tobj)
        x = (n.linea, n.columna, len(nombre))
        if c == "clase":
            info = self.info_clase(tobj)
            ms = self.miembro(info, nombre)
            if not ms:
                p = self.parecido(nombre, opciones=self.nombres_miembros(info))
                self.error(x, f"'{info.nombre}' no tiene un atributo llamado '{nombre}'",
                           (f"¿Quisiste decir '{p}'? " if p else "") + f"Revisa los miembros declarados en '{info.nombre}'.",
                           "Acceso a miembro", f"miembro de '{info.nombre}'", nombre)
                return DESCONOCIDO
            m = ms[0]
            self.verificar_acceso(m, x, info)
            if m.categoria == "método":
                self.error(x, f"'{nombre}' es un método de '{info.nombre}'; para usarlo faltan los paréntesis",
                           f"Escribe {nombre}(...) para llamarlo.", "Acceso a miembro", f"{nombre}()", nombre)
                return DESCONOCIDO
            if m.es_tipo:
                return DESCONOCIDO
            t = m.tipo
            if tobj.const and not m.estatico:
                t = replace(t, const=True)
            self.paso("Acceso a miembro", x, f"miembro de '{info.nombre}'", f"{m.categoria} {t}",
                      f"'{nombre}' es {art(m.categoria)} {m.acceso} de '{info.nombre}', de tipo {t}.")
            return t
        if c == "contenedor" and base(tobj.nombre) == "pair" and nombre in ("first", "second"):
            return self.elemento_contenedor(tobj, 0 if nombre == "first" else 1)
        if c in ("cadena", "contenedor"):
            b = "string" if c == "cadena" else base(tobj.nombre)
            tabla = METODOS_STRING if c == "cadena" else METODOS_VECTOR if b == "vector" else None
            if tabla is not None:
                if nombre in tabla:
                    self.error(x, f"'{nombre}' es un método de {b}; para usarlo faltan los paréntesis",
                               f"Escribe {nombre}().", "Acceso a miembro", f"{nombre}()", nombre)
                else:
                    self.error(x, f"{b} no tiene un miembro llamado '{nombre}'",
                               f"Algunos métodos de {b}: {', '.join(list(tabla)[:6])}.", "Acceso a miembro",
                               f"miembro de {b}", nombre)
            return DESCONOCIDO
        if c in LIBRES | {"flujo"}:
            return DESCONOCIDO
        self.error(x, f"'{self.texto(n.hijos[0] if n.hijos else None)}' es de tipo {tobj} y no tiene atributos",
                   "El operador '.' solo se usa con objetos (clases, structs, string, vector...).",
                   "Acceso a miembro", "objeto", str(tobj))
        return DESCONOCIDO

    def nombres_miembros(self, info):
        nombres, vistos, cola = set(), set(), [info]
        while cola:
            i = cola.pop()
            if i is None or i.nombre in vistos:
                continue
            vistos.add(i.nombre)
            nombres.update(i.miembros)
            cola.extend(self.clases.get(b) for b in i.bases)
        return list(nombres)

    def e_llamada(self, n):
        callee = n.hijos[0] if n.hijos else None
        args_n = n.hijos[1] if len(n.hijos) > 1 else None
        args = list(args_n.hijos) if args_n is not None else []
        if callee is None:
            return DESCONOCIDO
        if callee.tipo in ("AccesoMiembro", "AccesoPuntero"):
            tobj = self.objeto_de(callee)
            return self.llamar_metodo(n, callee, tobj, args, [self.tipo_arg(a) for a in args])
        if callee.tipo != "Identificador":
            self.expr(callee)
            for a in args:
                self.tipo_arg(a)
            return DESCONOCIDO
        targs = [self.tipo_arg(a) for a in args]
        nombre = callee.valor
        sims = self.buscar(nombre)
        if not sims:
            lib = self.biblioteca(nombre, callee)
            if lib is not None:
                return self.llamar_biblioteca(lib, args, targs, n, nombre)
            if self.cabeceras_locales:
                return DESCONOCIDO
            clave = (self.ctx.funcion.nombre if self.ctx and self.ctx.funcion else "global", nombre + "()")
            if clave not in self.reportados:
                self.reportados.add(clave)
                p = self.parecido(nombre)
                self.error(callee, f"La función '{nombre}' no está declarada",
                           (f"¿Quisiste decir '{p}'? " if p else "")
                           + "Declárala, o escribe su prototipo, antes del lugar donde la usas.",
                           "Llamada a función", f"'{nombre}' declarada", "no está en la tabla de símbolos")
            return DESCONOCIDO
        s = sims[0]
        if s.categoria in ("biblioteca", "tipo de biblioteca"):
            return self.llamar_biblioteca(s, args, targs, n, nombre.split("::")[-1])
        if s.es_tipo:
            if s.categoria in ("clase", "struct", "unión"):
                self.construir(self.clases.get(s.nombre), args, targs, n)
                return Tipo(s.nombre)
            if s.categoria == "alias":
                return s.tipo
            if s.categoria == "enumeración" and len(targs) == 1:
                return Tipo(s.nombre)
            return DESCONOCIDO
        if s.categoria in ("función", "método"):
            funcs = [f for f in sims if f.categoria in ("función", "método")]
            f = self.resolver_llamada(funcs, args, targs, n, f"'{nombre}'", nombre)
            if f is None:
                tipos = {str(x.tipo) for x in funcs}
                return funcs[0].tipo if len(tipos) == 1 else DESCONOCIDO
            if f.categoria == "método" and not f.estatico and self.ctx is not None and "::" not in nombre:
                if self.ctx.estatico:
                    self.error(callee, f"El método static '{self.ctx.funcion.nombre}' no puede llamar a '{nombre}' porque no es static",
                               "Llama al método a través de un objeto, o declara también ese método como static.",
                               "Llamada a método", "método static", "método normal")
                elif self.ctx.const and not f.metodo_const:
                    self.error(callee, f"El método const '{self.ctx.funcion.nombre}' no puede llamar a '{nombre}', que no es const",
                               f"Si '{nombre}' no modifica atributos, decláralo const: {f.tipo} {nombre}{self.firma(f)} const;",
                               "Llamada a método", "método const", "método no const")
            if f.clase and "::" in nombre:
                self.verificar_acceso(f, callee, self.clases.get(f.clase))
            return f.tipo
        c = self.cat(s.tipo)
        if c in LIBRES or (c == "clase" and self.miembro(self.info_clase(s.tipo), "operator()")):
            return DESCONOCIDO
        self.error(callee, f"'{nombre}' no es una función; es {art(s.categoria)} de tipo {s.tipo}",
                   "Quita los paréntesis si querías usar su valor.", "Llamada a función", "función",
                   f"{s.categoria} {s.tipo}")
        return DESCONOCIDO

    def llamar_metodo(self, n, acc, tobj, args, targs):
        nombre = acc.valor
        c = self.cat(tobj)
        x = (acc.linea, acc.columna, len(nombre))
        txt = self.texto(acc.hijos[0] if acc.hijos else None)
        if c == "clase":
            info = self.info_clase(tobj)
            ms = self.miembro(info, nombre)
            if not ms:
                p = self.parecido(nombre, opciones=self.nombres_miembros(info))
                self.error(x, f"La clase '{info.nombre}' no tiene un método llamado '{nombre}'",
                           (f"¿Quisiste decir '{p}'? " if p else "") + f"Revisa los métodos declarados en '{info.nombre}'.",
                           "Llamada a método", f"método de '{info.nombre}'", nombre)
                return DESCONOCIDO
            metodos = [m for m in ms if m.categoria == "método"]
            if not metodos:
                m = ms[0]
                if self.cat(m.tipo) in LIBRES:
                    return DESCONOCIDO
                self.error(x, f"'{nombre}' es un atributo de '{info.nombre}', no un método",
                           "Quita los paréntesis para usar su valor.", "Llamada a método", "método",
                           f"atributo {m.tipo}")
                return DESCONOCIDO
            f = self.resolver_llamada(metodos, args, targs, n, f"el método '{nombre}'", nombre)
            if f is None:
                tipos = {str(m.tipo) for m in metodos}
                return metodos[0].tipo if len(tipos) == 1 else DESCONOCIDO
            self.verificar_acceso(f, x, info)
            if tobj.const and not f.metodo_const and not f.estatico:
                self.error(x, f"No se puede llamar a '{nombre}' sobre '{txt}' porque el objeto es const y el método no lo es",
                           f"Si '{nombre}' no modifica el objeto, decláralo const: {f.tipo} {nombre}{self.firma(f)} const;",
                           "Llamada a método", "método const", "método no const")
            return f.tipo
        if c in ("cadena", "contenedor"):
            return self.metodo_biblioteca(n, acc, tobj, args, targs)
        if c in LIBRES | {"flujo"}:
            return DESCONOCIDO
        self.error(x, f"'{txt}' es de tipo {tobj} y no tiene métodos",
                   "Los métodos se usan con objetos de clases, string, vector, etc.", "Llamada a método",
                   "objeto", str(tobj))
        return DESCONOCIDO

    def metodo_biblioteca(self, n, acc, tobj, args, targs):
        nombre = acc.valor
        c = self.cat(tobj)
        b = "string" if c == "cadena" else base(tobj.nombre)
        tabla = METODOS_STRING if c == "cadena" else METODOS_VECTOR if b == "vector" else None
        if tabla is None:
            return DESCONOCIDO
        x = (acc.linea, acc.columna, len(nombre))
        txt = self.texto(acc.hijos[0] if acc.hijos else None)
        if nombre not in tabla:
            p = difflib.get_close_matches(nombre, list(tabla), 1, 0.7)
            self.error(x, f"{b} no tiene un método llamado '{nombre}'",
                       (f"¿Quisiste decir '{p[0]}'? " if p else "") + f"Algunos métodos de {b}: {', '.join(list(tabla)[:6])}.",
                       "Llamada a método", f"método de {b}", nombre)
            return DESCONOCIDO
        ret, mn, mx, modifica = tabla[nombre]
        k = len(targs)
        if k < mn or (mx is not None and k > mx):
            self.error(n, f"{b}::{nombre}() recibe {cuantos_txt(mn, mx)} y aquí recibe {k}",
                       f"Revisa cómo se usa {nombre}().", "Llamada a método", cuantos_txt(mn, mx), plural(k, "argumento"))
        elif modifica and tobj.const:
            self.error(x, f"No se puede usar {nombre}() con '{txt}' porque es constante y {nombre}() lo modifica",
                       "Quita const de la declaración si necesitas modificarlo.", "Llamada a método",
                       f"{b} modificable", f"const {b}")
        elif b == "vector" and nombre == "push_back" and k == 1:
            e = self.elemento_contenedor(tobj)
            if self.compatible(e, targs[0], args[0], "param"):
                self.paso("Llamada a método", n, str(e), str(targs[0]),
                          f"Se agrega un {targs[0]} al final de '{txt}' ({tobj}).")
            else:
                self.error(args[0], f"No se puede agregar un valor {targs[0]} a '{txt}', que guarda {e}",
                           self.sugerencia_tipos(e, targs[0], args[0]), "Llamada a método", str(e), str(targs[0]))
        else:
            self.paso("Llamada a método", n, f"método de {b}", f"{nombre}()",
                      f"'{nombre}' es un método de {b}" + (f" y devuelve {ret}." if ret not in ("?", "void") else "."))
        if ret == "E&":
            e = self.elemento_contenedor(tobj)
            return replace(e, ref=True, const=tobj.const or e.const)
        if ret == "char&":
            return Tipo("char", ref=True, const=tobj.const)
        return DESCONOCIDO if ret == "?" else texto_a_tipo(ret)


SENTENCIAS = {
    "Bloque": Analizador.s_bloque, "SentenciaVacía": lambda self, n: None,
    "DeclaraciónVariable": Analizador.s_declaracion, "SentenciaExpresión": Analizador.s_expresion,
    "If": Analizador.s_if, "While": Analizador.s_while, "DoWhile": Analizador.s_do,
    "For": Analizador.s_for, "ForRango": Analizador.s_for_rango, "Switch": Analizador.s_switch,
    "Return": Analizador.s_return, "Break": Analizador.s_break, "Continue": Analizador.s_continue,
    "Try": Analizador.s_try, "Throw": Analizador.s_throw,
}

EXPRESIONES = {
    "LiteralEntero": Analizador.e_literal, "LiteralFlotante": Analizador.e_literal,
    "LiteralCadena": Analizador.e_literal, "LiteralCarácter": Analizador.e_literal,
    "LiteralBooleano": Analizador.e_literal, "LiteralNulo": Analizador.e_literal,
    "Identificador": Analizador.e_ident, "Asignación": Analizador.e_asignacion,
    "Binaria": Analizador.e_binaria, "Ternario": Analizador.e_ternario,
    "Unaria": Analizador.e_unaria, "Postfijo": Analizador.e_postfijo,
    "Desreferencia": Analizador.e_desref, "Dirección": Analizador.e_direccion,
    "Sizeof": Analizador.e_sizeof, "Delete": Analizador.e_delete,
    "Conversión": Analizador.e_conversion, "ConversiónFuncional": Analizador.e_conv_funcional,
    "New": Analizador.e_new, "NewArreglo": Analizador.e_new, "This": Analizador.e_this,
    "ListaInicialización": Analizador.e_lista, "Índice": Analizador.e_indice,
    "AccesoMiembro": Analizador.e_acceso, "AccesoPuntero": Analizador.e_acceso,
    "Llamada": Analizador.e_llamada,
}


def analizar(arbol, tokens):
    """Punto de entrada que usa la interfaz."""
    return Analizador(arbol, tokens).ejecutar()


if __name__ == "__main__":
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from lexico import analizar as lex
    from sintactico import analizar as sint

    codigo = open(sys.argv[1], encoding="utf-8").read() if len(sys.argv) > 1 else sys.stdin.read()
    toks, errs = lex(codigo)
    if errs:
        print("Hay errores léxicos; el semántico no se ejecuta.")
        sys.exit(1)
    r = sint(toks)
    if r.errores:
        print("Hay errores sintácticos; el semántico no se ejecuta.")
        for e in r.errores:
            print(f"  {e['linea']}:{e['columna']}  {e['mensaje']}")
        sys.exit(1)
    res = analizar(r.arbol, toks)
    print(f"TABLA DE SÍMBOLOS ({len(res['simbolos'])})")
    print(f"  {'Nombre':<18} {'Categoría':<20} {'Tipo':<30} {'Ámbito':<24} Lín")
    for s in res["simbolos"]:
        print(f"  {s['nombre']:<18} {s['categoria']:<20} {s['tipo']:<30} {s['ambito']:<24} {s['linea']}")
    print(f"\nERRORES SEMÁNTICOS ({len(res['errores'])})")
    for e in res["errores"]:
        print(f"  {e['linea']}:{e['columna']}  {e['mensaje']}")
        if e["sugerencia"]:
            print(f"        → {e['sugerencia']}")
