package main

import (
	"fmt"
	"log"
	"net/http"
)

func handler(w http.ResponseWriter, r *http.Request) {
	fmt.Println(r.URL.RawQuery)
	fmt.Fprintf(w, `
<!DOCTYPE html>
<html>
<head>
<style>pre { font-family: monospace; font-size: 2em; white-space: pre; }</style>
</head>
<body>
<pre>
	><((((°>
	              ><((((°>

		><((((°>

  <°)))><	         ><((((°>
              <°)))><

        <°)))><         <')))))><

    Hello from a Compose Container!
</pre>
</body>
</html>
`)
}

func main() {
	http.HandleFunc("/", handler)
	log.Fatal(http.ListenAndServe(":8080", nil))
}
