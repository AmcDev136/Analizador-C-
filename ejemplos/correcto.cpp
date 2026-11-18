#include <iostream>
#include <vector>
#include <string>
#define MAX 100
using namespace std;

struct Punto {
    int x, y;
};

class Cuenta {
public:
    Cuenta(string titular, double saldo) : titular(titular), saldo(saldo) {}
    ~Cuenta() {}
    void depositar(double monto);
    double getSaldo() const { return saldo; }
private:
    string titular;
    double saldo;
};

void Cuenta::depositar(double monto) {
    if (monto > 0)
        saldo += monto;
    else
        cout << "Monto invalido" << endl;
}

int sumar(int a, int b) {
    int resultado = a + b;
    return resultado;
}

double promedio(const vector<int>& datos) {
    double suma = 0;
    for (size_t i = 0; i < datos.size(); i++) {
        suma += datos[i];
    }
    return datos.empty() ? 0 : suma / datos.size();
}

int main() {
    vector<int> numeros = {4, 8, 15, 16, 23};
    vector<vector<int>> matriz;
    int arreglo[5] = {1, 2, 3, 4, 5};
    Punto p = {3, 4};
    Cuenta* c = new Cuenta("Ana", 500.0);
    c->depositar(250);
    int total = sumar(4, 5);

    for (int n : numeros) {
        if (n % 2 == 0 && n > 5)
            total += n;
    }
    int i = 0;
    do {
        i++;
    } while (i < MAX && arreglo[i % 5] != 0);

    switch (total) {
        case 0: cout << "cero"; break;
        default: cout << "total: " << total << endl; break;
    }
    cout << "Promedio: " << promedio(numeros) << " x=" << p.x << endl;
    cout << (int) 3.7 << static_cast<double>(total) / 2 << endl;
    delete c;
    return 0;
}
