# Imagen frontend dev (Vite). El CMD es el dev-server con HMR; para
# producción usaríamos `npm run build` + nginx, fuera del MVP.
FROM node:20-alpine

WORKDIR /app

COPY package.json ./
RUN npm install

COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev"]