require("@nomiclabs/hardhat-ethers");

module.exports = {
  solidity: {
    compilers: [
      { version: "0.8.19" },
      { version: "0.8.0" }
    ]
  },
  networks: {
    logchain: {
      url: "http://127.0.0.1:8545",
      accounts: ["0x9c7bf0754e9b13d38d2b71a69da799f76545991b97918ae1e000f400437d51b2"],
      chainId: 12345
    }
  }
};