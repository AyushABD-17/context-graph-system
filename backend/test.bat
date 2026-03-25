curl.exe -X POST http://localhost:8000/query ^
  -H "Content-Type: application/json" ^
  -d "{\"message\": \"Which products appear in the most billing documents?\"}" > response.json
