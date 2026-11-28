"""Generador de código intermedio de tres direcciones para el compilador C++.

Entrada: Nodo raíz producido por sintactico.py.
Salida: dict con codigo (lista de instrucciones), texto y temporales.
El generador se ejecuta después de que léxico, sintaxis y semántica hayan terminado sin errores.
"""

class GeneradorCodigoIntermedio:
    def __init__(self):
        self.codigo = []
        self.temp = 0
        self.etiqueta = 0
        self.pila_ciclos = []

    def nuevo_temp(self):
        self.temp += 1
        return f"t{self.temp}"

    def nueva_etiqueta(self, prefijo="L"):
        self.etiqueta += 1
        return f"{prefijo}{self.etiqueta}"

    def emitir(self, instruccion):
        self.codigo.append(instruccion)

    def generar(self, arbol):
        self.visitar_programa(arbol)
        return {"codigo": self.codigo, "texto": "\n".join(self.codigo), "temporales": self.temp}

    def visitar_programa(self, nodo):
        for hijo in nodo.hijos:
            if hijo.tipo in ("Función", "Método", "Constructor", "Destructor"):
                self.visitar_funcion(hijo)
            elif hijo.tipo in ("DeclaraciónGlobal",):
                self.visitar_declaracion(hijo)

    def visitar_funcion(self, nodo):
        if not any(h.tipo == "Bloque" for h in nodo.hijos):
            return  # los prototipos no generan instrucciones
        self.emitir(f"\nfunc {nodo.valor}:")
        for h in nodo.hijos:
            if h.tipo == "Parámetros":
                for p in h.hijos:
                    if p.tipo == "Parámetro":
                        tipo = next((x.valor for x in p.hijos if x.tipo == "Tipo"), "?")
                        self.emitir(f"  param {p.valor or '_'} : {tipo}")
            elif h.tipo == "Bloque":
                self.visitar_bloque(h)
        self.emitir(f"end func {nodo.valor}")

    def visitar_bloque(self, nodo):
        for h in nodo.hijos:
            self.visitar_sentencia(h)

    def visitar_sentencia(self, n):
        t = n.tipo
        if t == "Bloque":
            self.visitar_bloque(n)
        elif t == "DeclaraciónVariable":
            self.visitar_declaracion(n)
        elif t in ("DeclaraciónGlobal",):
            self.visitar_declaracion(n)
        elif t == "SentenciaExpresión":
            if n.hijos: self.expresion(n.hijos[0])
        elif t == "Return":
            self.emitir("  return" if not n.hijos else f"  return {self.expresion(n.hijos[0])}")
        elif t == "If":
            self.generar_if(n)
        elif t == "While":
            self.generar_while(n)
        elif t == "DoWhile":
            self.generar_do(n)
        elif t == "For":
            self.generar_for(n)
        elif t == "Break":
            if self.pila_ciclos: self.emitir(f"  goto {self.pila_ciclos[-1][1]}")
        elif t == "Continue":
            if self.pila_ciclos: self.emitir(f"  goto {self.pila_ciclos[-1][0]}")
        elif t == "Switch":
            self.generar_switch(n)
        elif t in ("Try", "Throw"):
            self.emitir(f"  ; {t} (pendiente de lowering específico)")

    def visitar_declaracion(self, n):
        tipo = next((h.valor for h in n.hijos if h.tipo == "Tipo"), "auto")
        for v in (h for h in n.hijos if h.tipo == "Variable"):
            inicial = next((h for h in v.hijos if h.tipo not in ("Dimensión",)), None)
            nombre = v.valor.lstrip("*&")
            if inicial:
                self.emitir(f"  {nombre} = {self.expresion(inicial)}")
            else:
                self.emitir(f"  {nombre} = 0")

    def generar_if(self, n):
        cond = next((h for h in n.hijos if h.tipo == "Condición"), None)
        cuerpo = [h for h in n.hijos if h.tipo != "Condición"]
        sino = next((h for h in cuerpo if h.tipo == "Else"), None)
        entonces = next((h for h in cuerpo if h.tipo != "Else"), None)
        l_else, l_fin = self.nueva_etiqueta(), self.nueva_etiqueta()
        self.emitir(f"  ifFalse {self.expresion(cond.hijos[0])} goto {l_else}" if cond and cond.hijos else f"  goto {l_else}")
        if entonces: self.visitar_sentencia(entonces)
        if sino:
            self.emitir(f"  goto {l_fin}"); self.emitir(f"{l_else}:")
            for h in sino.hijos: self.visitar_sentencia(h)
            self.emitir(f"{l_fin}:")
        else: self.emitir(f"{l_else}:")

    def generar_while(self, n):
        ini, fin = self.nueva_etiqueta(), self.nueva_etiqueta()
        cond, cuerpo = n.hijos[0], n.hijos[1]
        self.emitir(f"{ini}:")
        self.emitir(f"  ifFalse {self.expresion(cond.hijos[0])} goto {fin}")
        self.pila_ciclos.append((ini, fin)); self.visitar_sentencia(cuerpo); self.pila_ciclos.pop()
        self.emitir(f"  goto {ini}"); self.emitir(f"{fin}:")

    def generar_do(self, n):
        ini, fin = self.nueva_etiqueta(), self.nueva_etiqueta()
        cuerpo, cond = n.hijos[0], n.hijos[1]
        self.emitir(f"{ini}:"); self.pila_ciclos.append((ini, fin))
        self.visitar_sentencia(cuerpo); self.pila_ciclos.pop()
        self.emitir(f"  if {self.expresion(cond.hijos[0])} goto {ini}"); self.emitir(f"{fin}:")

    def generar_for(self, n):
        if len(n.hijos) < 4: return
        init, cond, inc, cuerpo = n.hijos[:4]
        for h in init.hijos: self.visitar_sentencia(h) if h.tipo == "DeclaraciónVariable" else self.expresion(h)
        l_cond, l_inc, l_fin = self.nueva_etiqueta(), self.nueva_etiqueta(), self.nueva_etiqueta()
        self.emitir(f"{l_cond}:")
        if cond.hijos: self.emitir(f"  ifFalse {self.expresion(cond.hijos[0])} goto {l_fin}")
        self.pila_ciclos.append((l_inc, l_fin)); self.visitar_sentencia(cuerpo); self.pila_ciclos.pop()
        self.emitir(f"{l_inc}:")
        for h in inc.hijos: self.expresion(h)
        self.emitir(f"  goto {l_cond}"); self.emitir(f"{l_fin}:")

    def generar_switch(self, n):
        if not n.hijos: return
        valor = self.expresion(n.hijos[0].hijos[0])
        fin = self.nueva_etiqueta()
        casos = [(h, self.nueva_etiqueta("CASE")) for h in n.hijos[1:]]
        defecto = next((lab for h, lab in casos if h.tipo == "Default"), fin)
        for h, lab in casos:
            if h.tipo == "Case" and h.hijos:
                self.emitir(f"  if {valor} == {self.expresion(h.hijos[0])} goto {lab}")
        self.emitir(f"  goto {defecto}")
        self.pila_ciclos.append((fin, fin))
        for h, lab in casos:
            self.emitir(f"{lab}:")
            for st in h.hijos[1:] if h.tipo == "Case" else h.hijos:
                self.visitar_sentencia(st)
        self.pila_ciclos.pop(); self.emitir(f"{fin}:")

    def expresion(self, n):
        t, hijos = n.tipo, n.hijos
        if t in ("Identificador", "LiteralEntero", "LiteralFlotante", "LiteralCadena", "LiteralCarácter", "LiteralBooleano", "LiteralNulo", "This"):
            return n.valor
        if t == "Binaria" and len(hijos) == 2:
            a, b = self.expresion(hijos[0]), self.expresion(hijos[1])
            # Los operadores de flujo se representan como llamadas de E/S abstractas.
            if n.valor == "<<": self.emitir(f"  print {b}"); return a
            if n.valor == ">>": self.emitir(f"  read {b}"); return a
            tmp = self.nuevo_temp(); self.emitir(f"  {tmp} = {a} {n.valor} {b}"); return tmp
        if t == "Asignación" and len(hijos) == 2:
            izq, der = self.expresion(hijos[0]), self.expresion(hijos[1])
            op = n.valor
            if op == "=": self.emitir(f"  {izq} = {der}")
            else: self.emitir(f"  {izq} = {izq} {op[:-1]} {der}")
            return izq
        if t in ("Unaria", "Postfijo", "Desreferencia", "Dirección") and hijos:
            x = self.expresion(hijos[0]); tmp = self.nuevo_temp()
            if t == "Postfijo": self.emitir(f"  {tmp} = {x}; {x} = {x} {n.valor} 1")
            else: self.emitir(f"  {tmp} = {n.valor}{x}")
            return tmp
        if t == "Llamada" and len(hijos) >= 2:
            nombre = n.valor or self.expresion(hijos[0])
            args = hijos[1].hijos
            for a in reversed(args): self.emitir(f"  param {self.expresion(a)}")
            tmp = self.nuevo_temp(); self.emitir(f"  {tmp} = call {nombre}, {len(args)}"); return tmp
        if t == "Ternario" and len(hijos) == 3:
            tmp, falso, fin = self.nuevo_temp(), self.nueva_etiqueta(), self.nueva_etiqueta()
            self.emitir(f"  ifFalse {self.expresion(hijos[0])} goto {falso}")
            self.emitir(f"  {tmp} = {self.expresion(hijos[1])}"); self.emitir(f"  goto {fin}")
            self.emitir(f"{falso}:"); self.emitir(f"  {tmp} = {self.expresion(hijos[2])}"); self.emitir(f"{fin}:"); return tmp
        if t == "Índice" and len(hijos) == 2:
            return f"{self.expresion(hijos[0])}[{self.expresion(hijos[1])}]"
        if t in ("AccesoMiembro", "AccesoPuntero") and hijos:
            return f"{self.expresion(hijos[0])}{'.' if t == 'AccesoMiembro' else '->'}{n.valor}"
        if t in ("Conversión", "ConversiónFuncional") and hijos:
            return self.expresion(hijos[-1])
        if t == "ListaInicialización":
            return ", ".join(self.expresion(h) for h in hijos)
        if t == "Argumentos":
            return ", ".join(self.expresion(h) for h in hijos)
        return n.valor or "?"


def generar(arbol):
    """API pública de la fase de código intermedio."""
    return GeneradorCodigoIntermedio().generar(arbol)
