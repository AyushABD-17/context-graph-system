rmdir /s /q frontend
call npm create vite@latest frontend -- --template react
cd frontend
call npm install
call npm install react-force-graph-2d axios react-markdown
