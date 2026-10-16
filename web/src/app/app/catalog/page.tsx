"use client";

import { Catalog } from "../../../views/Skills";
import { useBoardData } from "../../../lib/board";

export default function CatalogPage() {
  return <Catalog repos={useBoardData().catalog} />;
}
