"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { IconeMapa, IconePorto, IconeResumo, Logo } from "./Icones";

// Barra lateral estreita e escura: a única superfície escura da interface.
// No celular vira uma faixa no topo.

const ITENS = [
  { href: "/", rotulo: "Mapa", Icone: IconeMapa },
  { href: "/resumo/", rotulo: "Resumo", Icone: IconeResumo },
  { href: "/portos/", rotulo: "Portos", Icone: IconePorto },
];

export default function Casca({ children }: { children: React.ReactNode }) {
  const caminho = usePathname() ?? "/";
  const ativo = (href: string) =>
    href === "/" ? caminho === "/" : caminho.startsWith(href) || (href === "/portos/" && caminho.startsWith("/porto"));

  return (
    <div className="casca">
      <a href="#conteudo" className="pular">Pular para o conteúdo</a>
      <nav className="trilho" aria-label="Navegação principal">
        <Link href="/" className="trilho-logo" aria-label="Info-Maré, início">
          <Logo />
        </Link>
        {ITENS.map(({ href, rotulo, Icone }) => (
          <Link key={href} href={href} className="trilho-item" aria-current={ativo(href) ? "page" : undefined}>
            <Icone />
            <span>{rotulo}</span>
          </Link>
        ))}
      </nav>
      <main id="conteudo" className="conteudo">
        {children}
      </main>
    </div>
  );
}
