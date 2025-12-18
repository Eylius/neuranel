#include <stdio.h>
#include <time.h>
int main() {
    long long sum = 0;
    long long n = 1000000000;
    clock_t start = clock();
    for (long long i = 1; i <= n; i++) {
        sum += i;   }
    clock_t end = clock();
    double time_spent = (double)(end - start) / CLOCKS_PER_SEC;
    printf("Summe: %lld\n", sum);
    printf("Zeit benötigt: %.4f Sekunden\n", time_spent);
    return 0;
}
