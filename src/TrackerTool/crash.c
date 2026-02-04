#include <stdio.h>

int main() {
    printf("Forcing crash...\n");

    int *p = NULL;
    *p = 42;   // 💥 Access violation (guaranteed crash)

    return 0;
}
