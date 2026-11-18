# Compilador de C++ en Python — léxico, sintáctico y semántico

Para ejecutarlo se necesita Python 3.10 o posterior con Tkinter (en Windows y macOS ya viene incluido; en Linux se instala con `sudo apt install python3-tk` o `sudo dnf install python3-tkinter`). No hace falta instalar nada más. Desde la carpeta del proyecto:

```
python interfaz.py
```

También se puede probar sin interfaz: `python sintactico.py ejemplos/correcto.cpp` imprime el árbol y los errores sintácticos, y `python semantico.py ejemplos/calculadora.cpp` imprime la tabla de símbolos y los errores semánticos.

## Archivos

`interfaz.py` es la ventana completa: editor con números de línea e indicadores L·S·M, tarjetas de las cinco fases, panel del proceso, pestañas (árbol, tokens, símbolos, errores, bitácora), animación paso a paso con retraso ajustable y exportación de un informe en .txt. `analizador_lexico.py` es el analizador léxico del equipo, sin ninguna modificación (también se puede seguir abriendo solo, con su propia ventana). `lexico.py` es un puente pequeño: ejecuta ese léxico, descarta los comentarios, traduce sus categorías (Palabra reservada, Identificador, Entero, Flotante, Cabecera…) a los tipos que usa el sintáctico y agrega la posición absoluta de cada token. `sintactico.py` es el analizador sintáctico de C++, de descenso recursivo y con recuperación de errores en modo pánico. `semantico.py` es el analizador semántico: recorre el árbol que genera el sintáctico, construye la tabla de símbolos por ámbitos y revisa los tipos. La carpeta `ejemplos/` trae cinco programas de prueba (uno correcto, uno con errores léxicos, uno con errores sintácticos y dos con errores semánticos) y se ve desde el botón Ejemplos.

Atajos: F5 compila, F6 pausa o continúa, F10 avanza un paso, Esc detiene.

## Cómo se unen los tres códigos

**Léxico.** Ya está integrado. Si el compañero actualiza su archivo, basta con reemplazar `analizador_lexico.py` por la versión nueva, siempre que conserve la clase `AnalizadorLexicoCPP` y los nombres de sus categorías de token. Si agrega una categoría nueva, hay que añadirla al diccionario `MAPA_TIPOS` de `lexico.py`.

**Semántico.** Ya está integrado en `semantico.py`. La interfaz lo detecta sola y lo ejecuta cuando no hay errores sintácticos. La función que llama es:

```python
def analizar(arbol, tokens):
    return {
        "simbolos": [  # se muestran en la pestaña Símbolos
            {"nombre": "sumar", "categoria": "función", "tipo": "int (int, int)",
             "ambito": "global", "linea": 5},
        ],
        "errores": [   # mismo formato que los demás errores
            {"fase": "Semántico", "mensaje": "'sumar' espera 2 argumentos y recibe 1",
             "linea": 14, "columna": 18, "sugerencia": "Agrega los argumentos que faltan.",
             "esperado": "(int, int)", "encontrado": "(int)", "regla": "Llamada a función"},
        ],
        "pasos": [     # la interfaz los anima uno por uno
            {"regla": "Llamada a función", "linea": 14, "columna": 18, "largo": 8,
             "esperado": "(int, int)", "encontrado": "(int)",
             "pila": ["global", "main"], "error": True, "mensaje": "..."},
            {"regla": "Declaración de variable", "linea": 11, "columna": 9, "largo": 5,
             "esperado": "'total' nuevo en «main»", "encontrado": "variable: int",
             "pila": ["global", "main"], "error": False, "mensaje": "...", "simbolo": 5},
        ],
    }
```

Cada paso con `"error": True` corresponde, en el mismo orden, a un elemento de `errores`. Un paso con la clave `simbolo` indica en qué momento se registró ese símbolo, y la interfaz lo agrega a la pestaña Símbolos en ese instante, así que la tabla se va llenando durante la animación.

El `arbol` que recibe es un `Nodo` de `sintactico.py` con `tipo`, `valor`, `hijos`, `linea` y `columna`. Los nodos más útiles para el semántico son `Función` (hijos: `Tipo`, `Parámetros`, `Bloque`), `Prototipo`, `Clase` y `Estructura` (con `Acceso`, `Campo`, `Método`, `Constructor`, `Destructor`), `DeclaraciónVariable` y `DeclaraciónGlobal` (hijos: `Tipo` y uno o más `Variable`; el valor de `Variable` incluye `*` o `&` si es puntero o referencia), `Asignación`, `Binaria` (el valor es el operador), `Llamada` (hijos: la expresión llamada y `Argumentos`), `Identificador` (con nombres calificados como `std::cout`) y los literales (`LiteralEntero`, `LiteralFlotante`, `LiteralCadena`, etc.). Para ver la estructura exacta de cualquier programa se puede usar `print(arbol.como_texto())`.

## Qué reconoce el sintáctico

En el nivel superior reconoce directivas del preprocesador (`#include <...>` o `"..."`, `#define` y las demás se leen hasta el fin de línea), `using namespace`, `namespace`, `typedef`, `enum` y `enum class`, plantillas sencillas (`template <typename T>`), clases, structs y uniones con herencia y especificadores de acceso, funciones, prototipos y variables globales. Dentro de las clases acepta campos, métodos (con `const`, `override`, `= 0`, `= default`), constructores con lista de inicialización, destructores, sobrecarga de operadores, y métodos y constructores definidos fuera de la clase (`Clase::metodo`). Los tipos pueden ser compuestos (`unsigned long long`), calificados (`std::string`), plantillas anidadas (`map<string, vector<int>>`), punteros, referencias y arreglos.

En las sentencias acepta declaraciones locales con inicialización por `=`, por `( )` o por `{ }`, `if/else`, `while`, `do-while`, `for` clásico y por rango (`for (int x : v)`), `switch/case/default`, `return`, `break`, `continue`, `try/catch` y `throw`. Las expresiones siguen la precedencia de C++: asignaciones compuestas, ternario, operadores lógicos y de bits, comparaciones, `<<` y `>>` (como en `cout << x`), aritméticos, unarios (`*p`, `&x`, `!`, `~`, `++`, `--`), `sizeof`, `new`/`delete`/`delete[]`, conversiones `(int) x` y `static_cast<T>(x)`, acceso con `.` y `->`, llamadas e índices. No soporta lambdas ni macros con parámetros.

Cuando encuentra un error, lo reporta donde un compilador lo marcaría (un `;` faltante se señala al final de la línea anterior) y se sincroniza para seguir buscando errores sin generar cascadas. Olvidar el `;` después de la `}` de una clase se reporta sin detener el análisis del resto del archivo.

## Qué revisa el semántico

Recorre el árbol en el mismo orden en que está escrito el programa, como un compilador de una sola pasada. Cada declaración se guarda en la tabla de símbolos del ámbito donde aparece (global, espacio de nombres, clase, función o bloque, por ejemplo `main › for`) y cada nombre que se usa se busca desde el ámbito más interno hacia afuera; al cerrar un bloque sus variables locales dejan de ser visibles. Al mismo tiempo calcula el tipo de cada expresión. Las clases se revisan en dos pasadas: primero se registran todos sus miembros y después se analizan los cuerpos de los métodos, porque en C++ un método puede usar atributos que están declarados más abajo.

Las verificaciones se agrupan así:

- **Nombres:** variables, funciones y tipos que se usan sin declararse (con sugerencia cuando hay un nombre parecido, por ejemplo `edda` → `edad`, o cuando la variable existe pero en otra función), redeclaraciones en el mismo ámbito, usar `cout`, `string` o `vector` sin `std` o sin su `#include`.
- **Tipos:** inicializaciones y asignaciones incompatibles (`string s = 5;`, `int n = "25";`, `char c = "a";`), operadores con tipos que no aceptan (`%` con `double`, `string + int`, sumar dos textos entre comillas, comparar `string` con `int`), condiciones que no se pueden evaluar como verdadero o falso, conversiones imposibles (`(int) texto`), pérdida de decimales dentro de llaves (`int k{3.7};`), punteros mezclados con valores, `cin >>` y `cout <<` al revés o sin variable.
- **Funciones:** número y tipo de argumentos, tomando en cuenta sobrecarga y valores por defecto; referencias que reciben un valor en lugar de una variable; `return` con el tipo incorrecto o con valor en una función `void`; funciones que deben devolver algo y no tienen `return`; funciones redefinidas o con prototipo distinto; `main` que no devuelve `int`; funciones conocidas de la biblioteca (`sqrt`, `pow`, `stoi`, `to_string`, `getline`, `max`…).
- **Variables y arreglos:** modificar una constante, constantes y referencias sin valor inicial, asignar a algo que no es variable (`5 = n;`), `auto` sin valor, variables `void`, tamaño de arreglo no entero o menor que uno, demasiados valores en la lista, índice constante fuera del arreglo, copiar un arreglo completo con `=`, texto más largo que un arreglo `char`.
- **Clases:** atributos o métodos que no existen, acceso a miembros `private` o `protected` desde fuera, `.` usado con punteros y `->` con objetos, constructores que no existen o que no reciben esos argumentos, objetos de clases abstractas, métodos `const` que modifican atributos, métodos definidos fuera de la clase que no coinciden con su prototipo, `override` sin método virtual en la base, atributos `const` que el constructor no inicializa.
- **Control:** `break` y `continue` fuera de un ciclo, `switch` con `double` o `string`, `case` repetidos, con decimales o con variables, recorrer con `for` de rango algo que no es un arreglo o contenedor, división entre cero constante.

Cuando el tipo de algo no se puede determinar (por ejemplo, lo que devuelve una función poco común de la biblioteca, o una expresión que ya tuvo un error) se marca como desconocido y se acepta en cualquier lugar. Así un error no provoca otros en cascada y no se marcan como incorrectos programas válidos. Cada error trae una sugerencia de cómo corregirlo, que aparece abajo de las pestañas al seleccionarlo.

`ejemplos/calculadora.cpp` tiene tres errores semánticos sencillos y `ejemplos/errores_semanticos.cpp` tiene uno distinto en casi cada línea de `main`, útil para la presentación.
