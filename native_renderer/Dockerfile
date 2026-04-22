FROM node:20-alpine

WORKDIR /app

COPY package.json ./
RUN npm install

COPY src ./src

EXPOSE 4100

CMD ["npm", "run", "start"]