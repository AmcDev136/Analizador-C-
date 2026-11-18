#include <iostream>
#include <string>
#include <vector>
using namespace std;

const double IVA = 0.16;

class Producto {
public:
    Producto(string nombre, double precio) : nombre(nombre), precio(precio) {}
    double getPrecio() const { return precio; }
    void aplicarDescuento(double porcentaje);
private:
    string nombre;
    double precio;
};

void Producto::aplicarDescuento(double porcentaje) {
    precio = precio - precio * porcentaje / 100;
}

int sumar(int a, int b) {
    return a + b;
}

double promedio(vector<int> datos) {
    int suma = 0;
    for (int x : datos)
        suma += x;
}

void saludar(string nombre) {
    cout << "Hola " << nombre << endl;
    return nombre;
}

int main() {
    Producto teclado("Teclado", 450.0);
    Producto mouse;
    teclado.precio = 300;
    teclado.aplicarDescuento("10");
    IVA = 0.08;
    int total = sumar(5);
    string mensaje = total;
    int residuo = 7.5 % 2;
    int dias[7] = {1, 2, 3, 4, 5, 6, 7, 8};
    dias[7] = 0;
    if (mensaje) {
        cout << resultado << endl;
    }
    double r = calcular(3.5);
    int x = 10;
    int x = 20;
    break;
    cout << teclado.getPrecio() * (1 + IVA) << endl;
    return "fin";
}
