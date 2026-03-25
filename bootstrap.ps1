$env:Path = [System.Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path","User")
Set-Location "d:\Doge-AI\sap-graph-system"
Remove-Item -Recurse -Force frontend -ErrorAction SilentlyContinue
npm.cmd create vite@latest frontend -- --template react
Set-Location "d:\Doge-AI\sap-graph-system\frontend"
npm.cmd install
npm.cmd install react-force-graph-2d axios react-markdown
Remove-Item -Force src\App.css
Remove-Item -Recurse -Force src\assets
Clear-Content src\index.css
Set-Content src\App.jsx "export default function App() { return <div>Hello</div> }"
