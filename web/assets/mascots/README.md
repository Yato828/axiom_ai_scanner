# Mascot variants

Three owner-supplied images, prepared as transparent PNGs with the built-in
imagegen edit tool (`transparent_background: true`). The originals in Downloads
are unchanged. Image roles and original dimensions are retained.

| Asset | Input file ending | Site placement |
| --- | --- | --- |
| `avatar.png` | `12_27_33.png` | Header avatar, favicon, footer avatar, token preview placeholder |
| `studio.png` | `12_27_44.png` | Mixer result placeholder |
| `hero.png` | `12_27_54.png` | Main hero |

Shared prompt, used separately for each edit:

> Use case: background-extraction. This is an edit of the supplied image, not a new illustration. Remove ONLY the black background and turn it into true alpha transparency, including all black negative spaces between the many arms, hands and fingers, around the head, and inside and around the floating eye symbol. Keep the figure itself exactly as supplied: identical pose, face, anatomy, hand positions, grayscale stone/pencil texture, shading, edges, details, framing and composition. Preserve dark shadows inside the body as opaque pixels. Keep the full figure and floating eye; preserve the input aspect ratio. Clean precise antialiased cutout with no background mat, no glow or halo, no black fringe, no text, no watermark. Do not redesign, beautify, relight, recolor, add, remove or redraw any body parts.

Exact additional sentence for each variant:

- Avatar: `Asset role: square portrait for the site avatar and favicon.`
- Studio: `Asset role: square seated composition for the image mixer and token preview.`
- Hero: `Asset role: vertical composition for the main hero and footer.`

Only the background is edited. CSS handles the placement, sizing and round avatar
crop. These assets do not replace user-uploaded token artwork or token icons.
