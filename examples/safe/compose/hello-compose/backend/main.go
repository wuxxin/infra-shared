package main

import (
	"fmt"
	"log"
	"net/http"
)

func handler(w http.ResponseWriter, r *http.Request) {
	fmt.Println(r.URL.RawQuery)
	fmt.Fprintf(w, `
	><((((°>

	              ><((((°>

		><((((°>

  <°)))><	         ><((((°>

              <°)))><

        <°)))><         <')))))><

Hello from a Compose Container!

`)
}

func main() {
	http.HandleFunc("/", handler)
	log.Fatal(http.ListenAndServe(":8080", nil))
}
