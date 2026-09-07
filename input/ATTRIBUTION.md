# Sample input image

`sample.jpg` is the official presidential portrait of Barack Obama
(Pete Souza, White House, December 2012), downscaled to 720x900.

* Source: https://commons.wikimedia.org/wiki/File:President_Barack_Obama.jpg
* Licence: **Public domain** — a work of the United States federal government
  prepared by an officer or employee as part of their official duties
  (17 U.S.C. § 105).

It ships with the repository so the pipeline can be run end to end immediately
after cloning, with no image sourcing step and no licensing question.

## Using your own image

```bash
python main.py --image path/to/your-photo.jpg
```

Anything you drop into `input/` other than `sample.jpg` is gitignored, so your
own photos are never committed to a public repository by accident.

Two practical notes:

* **Reverse image search only finds images that are publicly indexed.** A
  private individual's selfie will usually return no matches at all. That is a
  property of reverse image search, not a limitation of this pipeline — see
  "Limitations" in the main README.
* **One face per image works best.** If several faces are present the pipeline
  uses the largest and says so; cropping to the target face gives a cleaner
  result.
