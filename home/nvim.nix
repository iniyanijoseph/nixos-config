{ pkgs, animotion, ... }:
{
  programs.neovim = {
    enable = true;
    # Helix remains $EDITOR; Neovim is an explicitly invoked alternative.
    defaultEditor = false;
    viAlias = true;
    vimAlias = true;
    withNodeJs = true;
    withPython3 = false;
    withRuby = false;

    plugins = with pkgs.vimPlugins; [
      {
        plugin = pkgs.vimUtils.buildVimPlugin {
          pname = "animotion.nvim";
          version = "unstable";
          src = animotion;
        };
        type = "lua";
        config = ''
          require("AniMotion").setup({
            mode = "helix",
            clear_keys = { "<Esc>", "<A-Space>" },
            color = "Visual",
            map_visual = true,
          })
        '';
      }

      gruvbox-nvim
      nvim-treesitter.withAllGrammars
      plenary-nvim
      telescope-nvim
      nvim-lspconfig
      nvim-cmp
      cmp-nvim-lsp
      cmp-buffer
      cmp-path
      luasnip
      cmp_luasnip
      which-key-nvim
      gitsigns-nvim
      lualine-nvim
      nvim-web-devicons
      mini-nvim
      comment-nvim
    ];

    extraPackages = with pkgs; [
      ripgrep
      fd
      tinymist
      harper
      lua-language-server
      nil
      nixfmt
      typstyle
    ];

    initLua = ''
      vim.g.mapleader = " "
      vim.g.maplocalleader = " "

      vim.opt.number = true
      vim.opt.relativenumber = true
      vim.opt.mouse = "a"
      vim.opt.clipboard = "unnamedplus"
      vim.opt.breakindent = true
      vim.opt.undofile = true
      vim.opt.ignorecase = true
      vim.opt.smartcase = true
      vim.opt.signcolumn = "yes"
      vim.opt.updatetime = 250
      vim.opt.timeoutlen = 400
      vim.opt.splitright = true
      vim.opt.splitbelow = true
      vim.opt.wrap = true
      vim.opt.linebreak = true
      vim.opt.cursorline = true
      vim.opt.termguicolors = true

      vim.opt.guicursor = table.concat({
        "n-v-c:block",
        "i-ci-ve:ver25",
        "r-cr:hor20",
        "o:hor50",
      }, ",")

      require("gruvbox").setup({ contrast = "hard" })
      vim.cmd.colorscheme("gruvbox")

      require("mini.ai").setup()
      require("mini.surround").setup()
      require("mini.pairs").setup()
      require("Comment").setup()
      require("gitsigns").setup()
      require("which-key").setup()
      require("lualine").setup({
        options = { theme = "gruvbox", globalstatus = true },
        sections = {
          lualine_a = {
            "mode",
            function()
              local ok, selection = pcall(require, "AniMotion")
              return ok and selection.isActive() and "SEL" or ""
            end,
          },
        },
      })

      local cmp = require("cmp")
      local luasnip = require("luasnip")
      cmp.setup({
        snippet = {
          expand = function(args) luasnip.lsp_expand(args.body) end,
        },
        mapping = cmp.mapping.preset.insert({
          ["<C-Space>"] = cmp.mapping.complete(),
          ["<C-n>"] = cmp.mapping.select_next_item(),
          ["<C-p>"] = cmp.mapping.select_prev_item(),
          ["<CR>"] = cmp.mapping.confirm({ select = true }),
          ["<Tab>"] = cmp.mapping(function(fallback)
            if cmp.visible() then
              cmp.select_next_item()
            elseif luasnip.expand_or_jumpable() then
              luasnip.expand_or_jump()
            else
              fallback()
            end
          end, { "i", "s" }),
        }),
        sources = cmp.config.sources({
          { name = "nvim_lsp" },
          { name = "luasnip" },
          { name = "path" },
        }, {
          { name = "buffer" },
        }),
      })

      local capabilities = require("cmp_nvim_lsp").default_capabilities()
      local servers = {
        nil_ls = {},
        lua_ls = {
          settings = {
            Lua = { diagnostics = { globals = { "vim" } } },
          },
        },
        harper_ls = {},
        tinymist = {
          settings = {
            formatterMode = "typstyle",
            exportPdf = "onType",
            preview = {
              background = {
                enabled = true,
                args = {
                  "--data-plane-host=127.0.0.1:3635",
                  "--invert-colors=never",
                  "--open",
                },
              },
              cursorIndicator = true,
              scrollSync = true,
            },
          },
        },
      }

      for name, config in pairs(servers) do
        config.capabilities = capabilities
        vim.lsp.config(name, config)
        vim.lsp.enable(name)
      end

      vim.api.nvim_create_autocmd("LspAttach", {
        callback = function(event)
          local map = function(keys, action, description)
            vim.keymap.set("n", keys, action, {
              buffer = event.buf,
              desc = "LSP: " .. description,
            })
          end
          map("gd", vim.lsp.buf.definition, "definition")
          map("gy", vim.lsp.buf.type_definition, "type definition")
          map("gr", vim.lsp.buf.references, "references")
          map("gi", vim.lsp.buf.implementation, "implementation")
          map("K", vim.lsp.buf.hover, "hover")
          map("<leader>r", vim.lsp.buf.rename, "rename")
          map("<leader>a", vim.lsp.buf.code_action, "code action")
          map("<leader>=", function()
            vim.lsp.buf.format({ async = true })
          end, "format")
        end,
      })

      local telescope = require("telescope.builtin")
      local map = vim.keymap.set
      local silent = { silent = true }

      -- Match the user's Helix home-row layout: h moves right, l moves left.
      map({ "n", "x", "o" }, "h", "l", silent)
      map({ "n", "x", "o" }, "l", "h", silent)
      map({ "n", "x" }, "gh", "$", silent)
      map({ "n", "x" }, "gl", "0", silent)

      -- Helix-like selection/actions and the existing personal bindings.
      map("n", "x", "V", { desc = "Select line" })
      map("x", "x", ">", { desc = "Indent selection" })
      map("x", "<", "<gv", { desc = "Unindent selection" })
      map("n", "#", "gcc", { remap = true, desc = "Toggle comment" })
      map("x", "#", "gc", { remap = true, desc = "Toggle comment" })
      map("n", "<CR>", "o<Esc>", silent)
      map({ "n", "x" }, "<A-Space>", "<Esc>", silent)
      map({ "n", "x", "i" }, "<A-w>", "<Cmd>vsplit<CR>", silent)
      map({ "n", "x", "i" }, "<A-n>", "<C-w>w", silent)
      map({ "n", "x", "i" }, "<A-q>", "<Cmd>close<CR>", silent)

      map({ "n", "x" }, "<leader>w", "<Cmd>write<CR>", { desc = "Write" })
      map({ "n", "x" }, "<leader>x", "<Cmd>x<CR>", { desc = "Write and close" })
      map("n", "<leader>f", telescope.find_files, { desc = "Find files" })
      map("n", "<leader>/", telescope.live_grep, { desc = "Global search" })
      map("n", "<leader>b", telescope.buffers, { desc = "Buffers" })
      map("n", "<leader>s", telescope.lsp_document_symbols, { desc = "Symbols" })
      map("n", "<leader>d", vim.diagnostic.open_float, { desc = "Diagnostics" })

      vim.diagnostic.config({
        virtual_text = true,
        severity_sort = true,
        float = { border = "rounded", source = true },
      })
    '';
  };
}
