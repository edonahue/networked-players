import type { APIRoute } from "astro";
import type { AlbumV2, ChallengeV2 } from "../../../data/challenge";
import challengeData from "../../../../public/data/challenge.v3.json";
import { albumCard } from "../../../og/cards";
import { renderCard } from "../../../og/render";

export function getStaticPaths() {
  return (challengeData as ChallengeV2).albums.map((album) => ({
    params: { album: album.id },
    props: { album },
  }));
}

export const GET: APIRoute = ({ props }) =>
  renderCard(albumCard(props.album as AlbumV2));
